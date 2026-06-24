"""Build a rich HTML comparison report (baseline vs ours) from a suite run.

Input : results/<outdir>/summary.json  (from run_compare_suite.py)
Output: results/<outdir>/report.html   (self-contained: charts embedded as
        base64 PNG) + report.md (plain summary).

Charts produced (matplotlib, embedded):
  * Per-instance objective, grouped bars, log scale.
  * Per-instance objective gap vs baseline (signed %, lower=better for ours).
  * Weighted objective composition w1*Z1 / w2*Z2 / w3*Z3 per solver.
  * Raw Z1/Z2/Z3 per instance, small multiples.
  * Feasibility status grid.
  * Wall-clock per instance.
  * Scoreboard donut (wins / ties / losses) + R-nb point total.

Solution visualizations (bay layout + gantt) are generated separately by
tools/visualize.py; pass their PNG paths with --viz to embed them.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Korean labels in charts need a CJK-capable font (Windows ships Malgun Gothic);
# otherwise matplotlib renders tofu boxes. Fall back to DejaVu Sans if absent.
plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent

BLUE = "#3b6fb0"     # baseline
GREEN = "#2e9e5b"    # ours
RED = "#d6453d"
GREY = "#9aa0a6"


def _png_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def pivot(summary: dict):
    """Return {instance: {'baseline': res, 'our': res, ...meta}} ordered by num."""
    by_inst: dict[str, dict] = {}
    for r in summary["results"]:
        inst = r.get("instance", "?")
        by_inst.setdefault(inst, {})[r.get("solver")] = r
    def keyf(name):
        digits = "".join(c for c in name if c.isdigit())
        return int(digits) if digits else 0
    return {k: by_inst[k] for k in sorted(by_inst, key=keyf)}


def _obj(res):
    if (res and res.get("feasible") and not res.get("deadline_fail")
            and res.get("objective") is not None):
        return float(res["objective"])
    return None


def lower_bound(inst_path):
    """Provable *relaxation* lower bound on the weighted objective.

    Uses only the timing constraints ENTRY>=release and EXIT-ENTRY>=processing,
    so EXIT>=release+processing for every block, while IGNORING spatial packing,
    the crane (j>=k) rule, and the fact that one assignment cannot minimise all
    three Z-components at once. Therefore, with w1,w2,w3 >= 0:
        obj1 = Sigma max(0, exit-due)  >=  Sigma max(0, release+processing-due)
        obj2 >= 0 ,  obj3 >= 0
        objective >= w1 * Sigma max(0, release+processing-due)
    The true optimum is >= this value (usually by a wide margin -> a *loose* LB).
    Returns None if the instance file cannot be read.
    """
    try:
        d = json.loads(Path(inst_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    w = d.get("weights", {}) or {}
    w1 = float(w.get("w1", 0) or 0)
    z1 = 0.0
    n_late = 0
    for blk in d.get("blocks", []):
        slack = (blk.get("release_time", 0) + blk.get("processing_time", 0)
                 - blk.get("due_date", 0))
        if slack > 0:
            z1 += slack
            n_late += 1
    return {"z1_floor": z1, "n_late": n_late,
            "n_blocks": len(d.get("blocks", [])), "w1": w1,
            "total": w1 * z1}


def compute(piv):
    rows = []
    for inst, d in piv.items():
        b, o = d.get("baseline", {}), d.get("our", {})
        ob, oo = _obj(b), _obj(o)
        # winner under the score model: infeasible loses; lower objective wins.
        if ob is None and oo is None:
            winner = "both_fail"
        elif ob is None:
            winner = "our"
        elif oo is None:
            winner = "baseline"
        elif oo < ob:
            winner = "our"
        elif ob < oo:
            winner = "baseline"
        else:
            winner = "tie"
        gap = None
        if ob and oo is not None and ob != 0:
            gap = 100.0 * (oo - ob) / ob   # negative => ours better
        rows.append({
            "inst": inst,
            "n_blocks": b.get("n_blocks") or o.get("n_blocks"),
            "n_bays": b.get("n_bays") or o.get("n_bays"),
            "w1": b.get("w1") or o.get("w1"),
            "w2": b.get("w2") or o.get("w2"),
            "w3": b.get("w3") or o.get("w3"),
            "b": b, "o": o, "ob": ob, "oo": oo,
            "winner": winner, "gap": gap,
        })
    return rows


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def chart_objectives(rows):
    fig, ax = plt.subplots(figsize=(13, 5))
    x = np.arange(len(rows))
    w = 0.4
    bvals = [r["ob"] if r["ob"] else np.nan for r in rows]
    ovals = [r["oo"] if r["oo"] else np.nan for r in rows]
    ax.bar(x - w/2, bvals, w, label="baseline", color=BLUE)
    ax.bar(x + w/2, ovals, w, label="ours", color=GREEN)
    ax.set_yscale("log")
    # mark infeasible/missing at the axis bottom (x in data, y in axes fraction)
    tr = ax.get_xaxis_transform()
    for i, r in enumerate(rows):
        if r["ob"] is None:
            ax.text(i - w/2, 0.02, "✗", ha="center", va="bottom", color=RED,
                    fontsize=11, fontweight="bold", transform=tr)
        if r["oo"] is None:
            ax.text(i + w/2, 0.02, "✗", ha="center", va="bottom", color=RED,
                    fontsize=11, fontweight="bold", transform=tr)
    ax.set_xticks(x)
    ax.set_xticklabels([r["inst"].replace("prob_", "P") for r in rows], rotation=0, fontsize=8)
    ax.set_ylabel("objective (log scale, lower=better)")
    ax.set_title("Weighted objective per instance — baseline vs ours  (✗ = infeasible / timeout)")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    return _png_b64(fig)


def chart_gap(rows):
    fig, ax = plt.subplots(figsize=(13, 4.5))
    xs, gaps, cols = [], [], []
    for r in rows:
        if r["gap"] is None:
            continue
        xs.append(r["inst"].replace("prob_", "P"))
        gaps.append(r["gap"])
        cols.append(GREEN if r["gap"] < 0 else RED)
    ax.bar(xs, gaps, color=cols)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("ours vs baseline (%)\n← ours better | worse →")
    ax.set_title("Objective gap: (ours − baseline) / baseline  (negative = ours wins)")
    ax.grid(axis="y", alpha=0.3)
    for i, g in enumerate(gaps):
        ax.text(i, g, f"{g:+.0f}%", ha="center",
                va="bottom" if g >= 0 else "top", fontsize=7)
    return _png_b64(fig)


def chart_components(rows):
    """Weighted composition w1*Z1, w2*Z2, w3*Z3 stacked, baseline vs ours."""
    fig, ax = plt.subplots(figsize=(13, 5))
    x = np.arange(len(rows))
    w = 0.4
    def comp(res, k, wk):
        if (res and res.get(k) is not None and res.get("feasible")
                and not res.get("deadline_fail")):
            return float(res[k]) * float(res.get(wk, 1))
        return 0.0
    for off, side, hatch in [(-w/2, "b", None), (w/2, "o", "//")]:
        z1 = [comp(r[side], "obj1", "w1") for r in rows]
        z2 = [comp(r[side], "obj2", "w2") for r in rows]
        z3 = [comp(r[side], "obj3", "w3") for r in rows]
        ax.bar(x + off, z1, w, color="#c44", hatch=hatch, label="w1·Z1 tardiness" if off < 0 else None)
        ax.bar(x + off, z2, w, bottom=z1, color="#4488cc", hatch=hatch, label="w2·Z2 imbalance" if off < 0 else None)
        ax.bar(x + off, z3, w, bottom=np.array(z1)+np.array(z2), color="#88bb55", hatch=hatch, label="w3·Z3 pref" if off < 0 else None)
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels([r["inst"].replace("prob_", "P") for r in rows], fontsize=8)
    ax.set_title("Weighted objective composition (left bar=baseline, right hatched=ours)")
    ax.set_ylabel("weighted contribution (log)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    return _png_b64(fig)


def chart_z_components(rows):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    specs = [("obj1", "Z1 tardiness (Σ days late)"),
             ("obj2", "Z2 workload imbalance"),
             ("obj3", "Z3 preference penalty")]
    x = np.arange(len(rows))
    w = 0.4
    for ax, (k, title) in zip(axes, specs):
        bvals = [float(r["b"].get(k)) if r["b"].get("feasible") and not r["b"].get("deadline_fail") and r["b"].get(k) is not None else np.nan for r in rows]
        ovals = [float(r["o"].get(k)) if r["o"].get("feasible") and not r["o"].get("deadline_fail") and r["o"].get(k) is not None else np.nan for r in rows]
        ax.bar(x - w/2, bvals, w, label="baseline", color=BLUE)
        ax.bar(x + w/2, ovals, w, label="ours", color=GREEN)
        ax.set_title(title, fontsize=10)
        ax.set_xticks(x[::2])
        ax.set_xticklabels([rows[i]["inst"].replace("prob_", "P") for i in range(0, len(rows), 2)], fontsize=7)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=7)
    fig.suptitle("Raw objective components per instance", fontsize=12)
    return _png_b64(fig)


def chart_feasibility(rows):
    fig, ax = plt.subplots(figsize=(13, 1.8))
    grid = np.zeros((2, len(rows)))
    for i, r in enumerate(rows):
        grid[0, i] = 1 if r["b"].get("feasible") and not r["b"].get("deadline_fail") else 0
        grid[1, i] = 1 if r["o"].get("feasible") and not r["o"].get("deadline_fail") else 0
    cmap = plt.matplotlib.colors.ListedColormap([RED, GREEN])
    ax.imshow(grid, cmap=cmap, aspect="auto", vmin=0, vmax=1)
    ax.set_yticks([0, 1]); ax.set_yticklabels(["baseline", "ours"])
    ax.set_xticks(np.arange(len(rows)))
    ax.set_xticklabels([r["inst"].replace("prob_", "P") for r in rows], fontsize=8)
    ax.set_title("Judge OK (green = feasible within deadline, red = fail / timeout)")
    for i, r in enumerate(rows):
        for j, side in enumerate(["b", "o"]):
            ok = r[side].get("feasible") and not r[side].get("deadline_fail")
            ax.text(i, j, "✓" if ok else "✗",
                    ha="center", va="center", color="white", fontsize=8)
    return _png_b64(fig)


def chart_walltime(rows, timelimit=None):
    fig, ax = plt.subplots(figsize=(13, 4.2))
    x = np.arange(len(rows))
    w = 0.4
    bvals = [r["b"].get("wall") or r["b"].get("elapsed") or 0 for r in rows]
    ovals = [r["o"].get("wall") or r["o"].get("elapsed") or 0 for r in rows]
    ax.bar(x - w/2, bvals, w, label="baseline", color=BLUE)
    ocols = [RED if (r["o"].get("error") == "HARD_TIMEOUT" or r["o"].get("deadline_fail")) else GREEN for r in rows]
    ax.bar(x + w/2, ovals, w, label="ours", color=ocols)
    if timelimit:
        ax.axhline(timelimit, color="black", lw=1.4, ls="--",
                   label=f"timelimit {timelimit:.0f}s")
    ax.set_xticks(x)
    ax.set_xticklabels([r["inst"].replace("prob_", "P") for r in rows], fontsize=8)
    ax.set_ylabel("wall-clock (s)")
    ax.set_title("Run time per instance — ours (green/red=timeout-killed) vs budget")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    return _png_b64(fig)


def chart_scoreboard(rows):
    wins = sum(1 for r in rows if r["winner"] == "our")
    losses = sum(1 for r in rows if r["winner"] == "baseline")
    ties = sum(1 for r in rows if r["winner"] == "tie")
    bothfail = sum(1 for r in rows if r["winner"] == "both_fail")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    vals = [wins, ties, losses, bothfail]
    labels = [f"ours wins ({wins})", f"tie ({ties})", f"baseline wins ({losses})", f"both fail ({bothfail})"]
    cols = [GREEN, GREY, BLUE, RED]
    keep = [(v, l, c) for v, l, c in zip(vals, labels, cols) if v > 0]
    ax1.pie([k[0] for k in keep], labels=[k[1] for k in keep],
            colors=[k[2] for k in keep], autopct="%d%%", startangle=90,
            wedgeprops=dict(width=0.45))
    ax1.set_title("Head-to-head outcome")
    # R-nb point model (R=2): better solver +2, worse +1, tie both +2, fail -1.
    our_pts = base_pts = 0
    for r in rows:
        ob, oo = r["ob"], r["oo"]
        for side, val, other in [("our", oo, ob), ("base", ob, oo)]:
            if val is None:
                pts = -1
            else:
                nb = 1 if (other is not None and other < val) else 0
                pts = 2 - nb
            if side == "our":
                our_pts += pts
            else:
                base_pts += pts
    ax2.bar(["baseline", "ours"], [base_pts, our_pts], color=[BLUE, GREEN])
    ax2.set_title(f"Σ score (R−nb model, R=2)\nbaseline={base_pts}  ours={our_pts}")
    ax2.grid(axis="y", alpha=0.3)
    for i, v in enumerate([base_pts, our_pts]):
        ax2.text(i, v, str(v), ha="center", va="bottom", fontweight="bold")
    return _png_b64(fig), dict(wins=wins, ties=ties, losses=losses,
                               bothfail=bothfail, our_pts=our_pts, base_pts=base_pts)


def chart_lb_gap(rows):
    """Per-instance objective as a multiple of the theoretical lower bound.
    y=1 means a solver hit the (relaxation) floor. Only LB>0 instances shown."""
    fig, ax = plt.subplots(figsize=(13, 4.5))
    xs, br, orr = [], [], []
    for r in rows:
        lb = r.get("lb")
        if not lb or lb["total"] <= 0:
            continue
        xs.append(r["inst"].replace("prob_", "P"))
        br.append(r["ob"] / lb["total"] if r["ob"] else np.nan)
        orr.append(r["oo"] / lb["total"] if r["oo"] else np.nan)
    if not xs:
        ax.text(0.5, 0.62,
                "모든 인스턴스의 이론 하한 LB = 0",
                ha="center", va="center", fontsize=15, fontweight="bold")
        ax.text(0.5, 0.40,
                "모든 블록이 release+processing ≤ due → 완화상 불가피 지연 0.\n"
                "관측된 tardiness는 전적으로 공간·크레인(j≥k) 혼잡에서 발생.\n"
                "양수의 tight 하한을 보려면 CP/MIP 완화가 필요.",
                ha="center", va="center", fontsize=11)
        ax.axis("off")
        return _png_b64(fig)
    x = np.arange(len(xs))
    w = 0.4
    ax.bar(x - w/2, br, w, label="baseline ÷ LB", color=BLUE)
    ax.bar(x + w/2, orr, w, label="ours ÷ LB", color=GREEN)
    ax.axhline(1.0, color="black", lw=1.4, ls="--",
               label="이론 하한 (=1.0, 도달 시 최적 하한)")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(xs, fontsize=8)
    ax.set_ylabel("목적값 ÷ 이론 하한\n(낮을수록 하한에 근접)")
    ax.set_title("이론 하한(LB) 대비 배율 — 1.0이면 완화 하한에 도달  (실패 인스턴스 제외)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    return _png_b64(fig)


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def build_html(summary, rows, charts, sb, viz_imgs):
    def img(b64, cls="chart"):
        return f'<img class="{cls}" src="data:image/png;base64,{b64}"/>'

    # results table
    trs = []
    for r in rows:
        b, o = r["b"], r["o"]
        def cell(res):
            if res.get("deadline_fail"):
                return (f'<td class="fail">✗ deadline'
                        f'<br><span class="z">obj={res.get("objective")}</span>'
                        f'<br><span class="t">{res.get("wall", res.get("elapsed"))}s</span></td>')
            if not res.get("feasible"):
                err = res.get("error", "infeasible")
                return f'<td class="fail">✗ {err[:24]}</td>'
            return (f'<td class="ok">{res.get("objective"):,.0f}'
                    f'<br><span class="z">Z1={res.get("obj1")} Z2={res.get("obj2")} Z3={res.get("obj3")}</span>'
                    f'<br><span class="t">{res.get("wall", res.get("elapsed"))}s</span></td>')
        wcls = {"our": "wour", "baseline": "wbase", "tie": "wtie", "both_fail": "wfail"}[r["winner"]]
        wlabel = {"our": "OURS", "baseline": "BASE", "tie": "TIE", "both_fail": "—"}[r["winner"]]
        gap = f'{r["gap"]:+.1f}%' if r["gap"] is not None else "—"
        lb = r.get("lb")
        lbt = lb["total"] if lb else None
        lb_cell = f'{lbt:,.0f}' if lbt is not None else "—"
        def _ratio(val):
            if val is None or lbt is None or lbt <= 0:
                return "—"
            return f'×{val/lbt:,.1f}'
        oratio = _ratio(r["oo"])
        trs.append(
            f'<tr><td class="inst">{r["inst"]}</td>'
            f'<td>{r["n_blocks"]}×{r["n_bays"]}</td>'
            f'<td class="wts">{r["w1"]}/{r["w2"]}/{r["w3"]}</td>'
            f'<td class="lb">{lb_cell}</td>'
            f'{cell(b)}{cell(o)}'
            f'<td class="{wcls}">{wlabel}</td>'
            f'<td>{gap}</td>'
            f'<td class="lbr">{oratio}</td></tr>')
    table = "\n".join(trs)

    viz_html = ""
    for title, b64, caption in viz_imgs:
        viz_html += (f'<div class="vizblock"><h3>{title}</h3>{img(b64, "viz")}'
                     f'<p class="cap">{caption}</p></div>')

    tl = summary.get("timelimit")
    n = summary.get("n_instances")
    verdict = ("OURS dominates" if sb["our_pts"] > sb["base_pts"]
               else "BASELINE ahead" if sb["our_pts"] < sb["base_pts"]
               else "DEAD HEAT")

    # ---- diagnostic stats: ALL computed from the rendered rows (no hardcoding) ----
    def _jok(res):
        return bool(res.get("feasible") and not res.get("deadline_fail"))
    our_jok = sum(1 for r in rows if _jok(r["o"]))
    base_jok = sum(1 for r in rows if _jok(r["b"]))
    our_dead = sum(1 for r in rows if r["o"].get("deadline_fail"))
    our_inf = sum(1 for r in rows if not r["o"].get("feasible"))
    base_inf = sum(1 for r in rows if not r["b"].get("feasible"))
    our_ht = sum(1 for r in rows if r["o"].get("error") == "HARD_TIMEOUT")
    both = [r for r in rows if _jok(r["b"]) and _jok(r["o"]) and r["gap"] is not None]
    gaps = sorted(r["gap"] for r in both)
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    median_gap = gaps[len(gaps) // 2] if gaps else 0.0
    better = sum(1 for r in both if r["oo"] < r["ob"])
    worse = sum(1 for r in both if r["oo"] > r["ob"])
    tied = len(both) - better - worse
    best = min(both, key=lambda r: r["gap"]) if both else None
    worst = max(both, key=lambda r: r["gap"]) if both else None
    rescue = [r["inst"] for r in rows if _jok(r["o"]) and not _jok(r["b"])]
    our_miss = [(r["inst"],
                 "시간초과" if r["o"].get("deadline_fail") else "실현불가",
                 (r["o"].get("wall") or r["o"].get("elapsed") or 0))
                for r in rows if _jok(r["b"]) and not _jok(r["o"])]
    walls = [(r["o"].get("wall") or r["o"].get("elapsed")) for r in rows
             if (r["o"].get("wall") or r["o"].get("elapsed"))]
    wall_ratio = ((sum(walls) / len(walls)) / tl) if (walls and tl) else 0.0

    best_txt = f'{best["inst"]} {best["gap"]:.1f}%' if best else "—"
    worst_txt = f'{worst["inst"]} {worst["gap"]:+.1f}%' if worst else "—"
    rescue_txt = ", ".join(rescue) if rescue else "없음"
    miss_txt = (", ".join(f'{i}({k} {w:.0f}s)' for i, k, w in our_miss)
                if our_miss else "없음")
    verdict_word = ("우리 우위" if sb["our_pts"] > sb["base_pts"]
                    else "baseline 우위" if sb["our_pts"] < sb["base_pts"] else "동률")

    # theoretical lower-bound (LB) summary
    lb_ratios = [(r["inst"], r["oo"] / r["lb"]["total"]) for r in rows
                 if r.get("lb") and r["lb"]["total"] > 0 and r["oo"] is not None]
    mean_lb_ratio = (sum(x for _, x in lb_ratios) / len(lb_ratios)) if lb_ratios else None
    best_lb = min(lb_ratios, key=lambda t: t[1]) if lb_ratios else None
    lb_zero = sum(1 for r in rows if r.get("lb") and r["lb"]["total"] == 0)
    lb_na = sum(1 for r in rows if not r.get("lb"))
    if mean_lb_ratio is not None:
        lb_line = (f'LB&gt;0 인스턴스에서 우리 해는 이론 하한의 평균 <b>×{mean_lb_ratio:,.1f}</b>'
                   + (f' (최소 {best_lb[0]} ×{best_lb[1]:,.1f})' if best_lb else '')
                   + f'; LB=0(불가피 지연 없음) {lb_zero}개'
                   + (f', LB 미산출 {lb_na}개' if lb_na else ''))
    else:
        lb_line = '전 인스턴스 LB=0 — 완화 기준상 모든 블록 정시 가능(불가피 지연 0)이라 하한이 0'

    diag = f"""
 <section><h2>진단 요약 (데이터 기반)</h2>
  <div class="note"><b>핵심:</b> 학습 인스턴스 {n}개 · timelimit {tl:.0f}s 기준, 우리 솔버는
   <b>judge-OK {our_jok}/{n}</b> (baseline {base_jok}/{n}). 두 솔버가 모두 제한 내 완료한
   <b>{len(both)}개</b> 구간에서 우리 목적함수가 평균 <b>{mean_gap:+.1f}%</b>(음수 = 우리가 더 낮음/우위),
   우위 {better} · 동률 {tied} · 열위 {worse}. R−nb 점수 <b>ours {sb['our_pts']} vs baseline {sb['base_pts']}</b>
   → 종합 <b>{verdict_word}</b>.</div>
  <ul>
   <li><b>강점 — baseline 실패 구제</b>: baseline이 실현불가(infeasible)였던
       <b>{len(rescue)}개</b>({rescue_txt})를 우리는 실현가능하게 해결. 점수모델상 baseline에
       −1을 안기던 인스턴스라 가장 큰 이득의 원천.</li>
   <li><b>개선 폭</b>: 양쪽 완료 구간 최대 개선 <b>{best_txt}</b>, 최악 {worst_txt},
       중앙값 격차 {median_gap:+.1f}%.</li>
   <li><b>약점 — 시간 예산</b>: 우리만 제한을 못 지킨 인스턴스 <b>{len(our_miss)}개</b>({miss_txt}).
       이들은 <b>실현가능 해를 이미 찾았고</b> 다만 로컬 {tl:.0f}s 예산을 근소하게 넘김(실현불가 아님).
       genuine infeasible {our_inf}개 · hard-timeout {our_ht}개 · 평균 실행시간/예산 비율 {wall_ratio:.2f}.</li>
   <li><b>대회 영향</b>: 실서버 한도는 인스턴스당 수 분~30분으로 로컬 {tl:.0f}s보다 훨씬 넉넉하므로
       위 시간초과 {our_dead}개는 실서버에서 통과 가능성이 높다. 다만 한 인스턴스라도 한도 초과 시
       <b>−1</b>(평균 R/2 손실)이라, 시간가드 마진 확보가 안전.</li>
   <li><b>이론 하한 대비</b>: {lb_line}. 하한 LB = w1·Σmax(0, release+processing−due)로
       공간·크레인(j≥k) 제약을 무시한 <b>완화 하한</b> — 실제 최적은 이 값 이상(보통 훨씬 큼).
       Z2·Z3 하한은 0.</li>
  </ul>
 </section>"""

    reco_items = []
    if our_miss:
        reco_items.append(
            f"<li><b>시간가드 마진 확보 (최우선)</b>: 시간초과 {len(our_miss)}개({miss_txt})는 "
            f"feasible 해를 이미 찾았다 — 로컬 {tl:.0f}s를 근소 초과했을 뿐. anytime 구조에서 "
            f"'예산의 80~90% 시점에 현재 최선해를 확정 반환'하는 마감 가드를 넣어 실서버에서도 "
            f"−1을 원천 차단.</li>")
    if our_inf:
        reco_items.append(
            f"<li><b>genuine infeasible 제거</b>: 실현불가 {our_inf}개는 디코더가 유효해를 못 낸 "
            f"경우 — feasibility 최우선의 안전 폴백(예: baseline 해) 보장.</li>")
    if rescue:
        reco_items.append(
            f"<li><b>강점 회귀 고정</b>: baseline이 실패하는 {len(rescue)}개({rescue_txt})에서의 "
            f"우위가 점수의 핵심 동력 — 이 구간을 회귀 테스트로 잠금.</li>")
    if worse:
        reco_items.append(
            f"<li><b>열위 구간 분석</b>: 양쪽 완료 중 우리가 진 {worse}개({worst_txt})의 원인"
            f"(주로 Z1 tardiness 가중 w1이 큼)을 분해해 디코드 휴리스틱 보강.</li>")
    reco_items.append(
        "<li><b>데이터 최신성</b>: 본 리포트는 기존 비교 스위트(summary.json) 수치다. 솔버 코드가 "
        "이후 변경됐다면 동일 인스턴스로 재실행해 수치를 갱신할 것.</li>")
    reco = ("\n <section><h2>권고 (우선순위)</h2>\n  <ol>\n   "
            + "\n   ".join(reco_items) + "\n  </ol>\n </section>")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>OGC 2026 — baseline vs ours (new instances)</title>
<style>
 body{{font-family:'Segoe UI',system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1c2733}}
 header{{background:#16324f;color:#fff;padding:28px 40px}}
 header h1{{margin:0 0 6px;font-size:24px}} header p{{margin:0;opacity:.85}}
 .wrap{{max-width:1180px;margin:0 auto;padding:24px 28px 80px}}
 .kpis{{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0}}
 .kpi{{background:#fff;border-radius:10px;padding:16px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08);flex:1;min-width:150px}}
 .kpi .n{{font-size:30px;font-weight:700}} .kpi .l{{color:#5a6b7b;font-size:13px}}
 .kpi.win .n{{color:{GREEN}}} .kpi.lose .n{{color:{BLUE}}} .kpi.bad .n{{color:{RED}}}
 .verdict{{font-size:18px;font-weight:700;background:#fff;border-left:6px solid {GREEN};padding:14px 18px;border-radius:6px;margin:10px 0 24px}}
 section{{background:#fff;border-radius:10px;padding:20px 24px;margin:18px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 section h2{{margin:0 0 14px;font-size:18px;border-bottom:2px solid #eef1f4;padding-bottom:8px}}
 img.chart{{width:100%;height:auto;border:1px solid #eef1f4;border-radius:6px}}
 img.viz{{width:100%;height:auto;border:1px solid #ddd;border-radius:6px}}
 .vizblock{{margin:18px 0}} .vizblock h3{{margin:0 0 8px;font-size:15px}}
 .cap{{color:#5a6b7b;font-size:13px;margin:6px 0 0}}
 table{{width:100%;border-collapse:collapse;font-size:13px}}
 th,td{{padding:8px 10px;text-align:center;border-bottom:1px solid #eef1f4}}
 th{{background:#16324f;color:#fff;position:sticky;top:0}}
 td.inst{{font-weight:700;text-align:left}} td.ok{{color:#16324f}} td.fail{{color:{RED};font-weight:600}}
 td.wour{{background:{GREEN};color:#fff;font-weight:700}} td.wbase{{background:{BLUE};color:#fff;font-weight:700}}
 td.wtie{{background:{GREY};color:#fff}} td.wfail{{background:{RED};color:#fff}}
 .z{{color:#7a8a99;font-size:11px}} .t{{color:#aab3bd;font-size:11px}} .wts{{color:#5a6b7b;font-size:11px}}
 td.lb{{color:#5b4bb5;font-weight:600}} td.lbr{{color:#5a6b7b;font-weight:600}}
 .note{{background:#fff8e6;border-left:5px solid #e0a800;padding:12px 16px;border-radius:6px;font-size:14px;margin:10px 0}}
</style></head><body>
<header><h1>OGC 2026 — 신규 학습 인스턴스: 공식 baseline vs 우리 알고리즘</h1>
<p>학습 인스턴스 {n}개 (prob_1…prob_{n}) · timelimit {tl:.0f}s · 채점 utils: floor(Z2) · 데이터: 기존 비교 스위트(summary.json)</p></header>
<div class="wrap">
 <div class="verdict">결과: {verdict} &nbsp;|&nbsp; 우리 승 {sb['wins']} · 무 {sb['ties']} · 패 {sb['losses']} · 양쪽실패 {sb['bothfail']}  (R−nb 점수 baseline {sb['base_pts']} / ours {sb['our_pts']})</div>
 <div class="kpis">
  <div class="kpi win"><div class="n">{sb['wins']}/{n}</div><div class="l">우리가 더 나은 인스턴스</div></div>
  <div class="kpi"><div class="n">{sb['ties']}</div><div class="l">동점</div></div>
  <div class="kpi lose"><div class="n">{sb['losses']}</div><div class="l">baseline이 더 나은 인스턴스</div></div>
  <div class="kpi bad"><div class="n">{our_dead + our_inf}</div><div class="l">우리 미달 (시간초과 {our_dead}·실현불가 {our_inf})</div></div>
 </div>
 {diag}
 <section><h2>① 인스턴스별 목적함수</h2>{img(charts['obj'])}</section>
 <section><h2>② 목적함수 격차 (음수 = 우리 승)</h2>{img(charts['gap'])}</section>
 <section><h2>③ 가중 목적함수 구성 (w1·Z1 / w2·Z2 / w3·Z3)</h2>{img(charts['comp'])}
   <p class="cap">w1이 매우 커서(수만 단위) Z1(지연)이 점수를 지배함을 확인.</p></section>
 <section><h2>④ 원시 목적 성분 Z1 / Z2 / Z3</h2>{img(charts['zcomp'])}</section>
 <section><h2>⑤ 실현가능성 그리드</h2>{img(charts['feas'])}
   <p class="cap">−1(실현불가)은 대회 점수에서 치명적 — 한 인스턴스라도 빨강이면 평균 R/2 손실.</p></section>
 <section><h2>⑥ 실행 시간</h2>{img(charts['wall'])}</section>
 <section><h2>⑦ 종합 스코어보드</h2>{img(charts['score'])}</section>
 <section><h2>⑧ 이론 하한(LB) 대비 — optimality gap</h2>{img(charts['lb'])}
   <p class="cap">LB = w1·Σmax(0, release+processing−due). EXIT≥release+processing 만 사용한 <b>완화 하한</b>이라
   공간·크레인(j≥k) 제약과 세 성분 동시최소화 불가를 무시 → 실제 최적은 이 값 이상(보통 훨씬 큼). Z2·Z3 하한=0.
   막대가 1.0(점선)에 가까울수록 하한에 근접.</p></section>
 <section><h2>⑨ 해(solution) 시각화 — bay 배치 + Gantt</h2>{viz_html or '<p>—</p>'}</section>
 <section><h2>⑩ 상세 결과 표</h2>
  <table><thead><tr><th>instance</th><th>n×bays</th><th>w1/w2/w3</th><th>이론 하한<br>LB</th>
   <th>baseline</th><th>ours</th><th>winner</th><th>gap<br>(vs base)</th><th>ours<br>÷LB</th></tr></thead>
   <tbody>{table}</tbody></table>
   <p class="cap">LB = 이론 하한(완화, w1·Σmax(0,release+processing−due)). 「ours÷LB」 = 우리 목적값이 하한의 몇 배인지(작을수록 최적 근접; LB=0이면 —).</p></section>
 {reco}
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    ap.add_argument("--instances-glob", default="instances/train/prob_*.json",
                    help="glob to locate instance JSONs for the theoretical lower bound")
    ap.add_argument("--viz", nargs="*", default=[],
                    help="title::pngpath::caption triples to embed")
    args = ap.parse_args()

    sm_path = Path(args.summary)
    summary = json.loads(sm_path.read_text(encoding="utf-8"))
    piv = pivot(summary)
    rows = compute(piv)

    # attach theoretical lower bound per instance (loads instance JSON files)
    lb_paths = {p.stem: p for p in ROOT.glob(args.instances_glob)}
    for r in rows:
        p = lb_paths.get(r["inst"])
        r["lb"] = lower_bound(p) if p else None

    score_b64, sb = chart_scoreboard(rows)
    charts = {
        "obj": chart_objectives(rows),
        "gap": chart_gap(rows),
        "comp": chart_components(rows),
        "zcomp": chart_z_components(rows),
        "feas": chart_feasibility(rows),
        "wall": chart_walltime(rows, summary.get("timelimit")),
        "score": score_b64,
        "lb": chart_lb_gap(rows),
    }
    viz_imgs = []
    for spec in args.viz:
        parts = spec.split("::")
        if len(parts) == 3 and Path(parts[1]).exists():
            b64 = base64.b64encode(Path(parts[1]).read_bytes()).decode("ascii")
            viz_imgs.append((parts[0], b64, parts[2]))

    html = build_html(summary, rows, charts, sb, viz_imgs)
    out_html = sm_path.parent / "report.html"
    out_html.write_text(html, encoding="utf-8")

    # plain markdown summary
    md = [f"# OGC2026 baseline vs ours — new instances (timelimit {summary.get('timelimit')}s)\n",
          f"Outcome: ours wins {sb['wins']}, ties {sb['ties']}, losses {sb['losses']}, both-fail {sb['bothfail']}.",
          f"R-nb score: baseline {sb['base_pts']}, ours {sb['our_pts']}.\n",
          "이론 하한 LB = w1·Σmax(0, release+processing−due) (완화 하한; 실제 최적 ≥ LB). Z2·Z3 하한=0.\n",
          "| instance | n×bays | w1/w2/w3 | LB(이론하한) | baseline obj | ours obj | winner | gap | ours÷LB |",
          "|---|---|---|---|---|---|---|---|---|"]
    def _md_obj(res, val):
        if val is not None:
            return f'{val:,.0f}'
        if res.get("deadline_fail"):
            w = res.get("wall") or res.get("elapsed") or 0
            o = res.get("objective")
            return (f'시간초과({w:.0f}s, obj={o:,.0f})' if o is not None
                    else f'시간초과({w:.0f}s)')
        return 'INFEASIBLE'
    for r in rows:
        bo = _md_obj(r["b"], r["ob"])
        oo = _md_obj(r["o"], r["oo"])
        gap = f'{r["gap"]:+.1f}%' if r["gap"] is not None else "—"
        lb = r.get("lb")
        lbt = lb["total"] if lb else None
        lb_s = f'{lbt:,.0f}' if lbt is not None else "—"
        oratio = (f'×{r["oo"]/lbt:,.1f}'
                  if (lbt and lbt > 0 and r["oo"] is not None) else "—")
        md.append(f'| {r["inst"]} | {r["n_blocks"]}×{r["n_bays"]} | {r["w1"]}/{r["w2"]}/{r["w3"]} | {lb_s} | {bo} | {oo} | {r["winner"]} | {gap} | {oratio} |')
    (sm_path.parent / "report.md").write_text("\n".join(md), encoding="utf-8")

    print(f"[report] {out_html}")
    print(f"[report] {sm_path.parent/'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
