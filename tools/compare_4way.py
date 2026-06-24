"""4-way (5-column) comparison for OGC2026 train instances.

Columns per instance:  수학적 최소(LB) | baseline 6/3 | baseline 현재 | ours 6/3 | ours 현재
Each solver cell shows the weighted objective and its components Z1/Z2/Z3
(= the user's t1/t2/t3 : tardiness / workload-imbalance / preference penalty).

LB = w1 * Sigma max(0, release+processing-due)  (relaxation lower bound; Z2,Z3 floor 0).
Baseline is shown for BOTH runs because the official greedy is time-sensitive and its
numbers swing run-to-run (the same +-20x non-determinism that affects ours on large bays).

Usage:
  python tools/compare_4way.py --old results/compare_HONEST_seq_tl60/summary.json \
      --new results/compare_current_20260604/summary.json \
      [--instances-glob instances/train/prob_*.json] [--out results/.../compare_4way.html]
"""
from __future__ import annotations
import argparse, json, html
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GREEN, BLUE, GREY, RED, GOLD = "#2e9e5b", "#3b6fb0", "#9aa0a6", "#d6453d", "#b9860b"


def load(p):
    s = json.loads(Path(p).read_text(encoding="utf-8"))
    by = {}
    for r in s["results"]:
        by.setdefault(r.get("instance"), {})[r.get("solver")] = r
    return by, s


def keyf(n):
    d = "".join(c for c in n if c.isdigit())
    return int(d) if d else 0


def lower_bound(inst_path):
    try:
        d = json.loads(Path(inst_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    w1 = float((d.get("weights", {}) or {}).get("w1", 0) or 0)
    z1 = sum(max(0.0, b.get("release_time", 0) + b.get("processing_time", 0)
                 - b.get("due_date", 0)) for b in d.get("blocks", []))
    return {"objective": w1 * z1, "obj1": z1, "obj2": 0.0, "obj3": 0.0, "lb": True}


def jok(r):
    return bool(r and r.get("feasible") and not r.get("deadline_fail"))


def status(r):
    if r is None:
        return "—"
    if jok(r):
        return "OK"
    return "DEADLINE" if r.get("deadline_fail") else "INFEAS"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="6/3 summary.json")
    ap.add_argument("--new", required=True, help="current summary.json")
    ap.add_argument("--instances-glob", default="instances/train/prob_*.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    old, sO = load(args.old)
    new, sN = load(args.new)
    lb_paths = {p.stem: p for p in ROOT.glob(args.instances_glob)}
    insts = sorted(set(old) | set(new), key=keyf)

    # columns: (key, label, css)  -- order matters
    COLS = [
        ("lb",    "수학적 최소 LB",  "lb"),
        ("b_old", "baseline 6/3",   "base"),
        ("b_new", "baseline 현재",  "base"),
        ("o_old", "ours 6/3",       "ours"),
        ("o_new", "ours 현재",      "ours"),
    ]

    def rec(inst, key):
        if key == "lb":
            p = lb_paths.get(inst)
            return lower_bound(p) if p else None
        run, solver = ({"b_old": (old, "baseline"), "o_old": (old, "our"),
                        "b_new": (new, "baseline"), "o_new": (new, "our")})[key]
        return run.get(inst, {}).get(solver)

    # ---- build rows ----
    trs = []
    agg = {k: {"ok": 0, "n": 0} for k, _, _ in COLS}
    for inst in insts:
        recs = {k: rec(inst, k) for k, _, _ in COLS}
        # weights from any record that has them
        w1 = w2 = w3 = None
        nb = nbay = None
        for k in ("o_new", "o_old", "b_new", "b_old"):
            r = recs.get(k)
            if r and r.get("w1") is not None:
                w1, w2, w3 = r.get("w1"), r.get("w2"), r.get("w3")
                nb, nbay = r.get("n_blocks"), r.get("n_bays")
                break
        # winner = min objective among the 4 REAL solvers that are judge_ok
        real = {k: recs[k] for k in ("b_old", "b_new", "o_old", "o_new")}
        feas_objs = {k: float(r["objective"]) for k, r in real.items()
                     if jok(r) and r.get("objective") is not None}
        best_key = min(feas_objs, key=feas_objs.get) if feas_objs else None

        cells = []
        for k, _, _ in COLS:
            r = recs[k]
            agg[k]["n"] += 1 if k != "lb" else 0
            if jok(r) and k != "lb":
                agg[k]["ok"] += 1
            cells.append(_cell(k, r, best_key == k))
        delta = ""
        ro, rn = real["o_old"], real["o_new"]
        if jok(ro) and jok(rn) and ro.get("objective"):
            d = 100.0 * (float(rn["objective"]) - float(ro["objective"])) / float(ro["objective"])
            cls = "up" if d > 1 else "down" if d < -1 else "flat"
            delta = f'<span class="d {cls}">{d:+.1f}%</span>'
        elif status(ro) != status(rn):
            delta = f'<span class="d chg">{status(ro)}→{status(rn)}</span>'
        else:
            delta = '<span class="d flat">—</span>'

        trs.append(
            f'<tr><td class="inst">{html.escape(inst)}</td>'
            f'<td class="nb">{nb}×{nbay}</td>'
            f'<td class="wts">{w1}/{w2}/{w3}</td>'
            + "".join(cells)
            + f'<td class="delta">{delta}</td></tr>')

    header_cells = "".join(f'<th class="{css}">{html.escape(lbl)}</th>' for _, lbl, css in COLS)
    table = (
        '<table><thead><tr>'
        '<th>instance</th><th>n×bays</th><th>w1/w2/w3</th>'
        + header_cells +
        '<th>ours<br>6/3→현재</th></tr>'
        '<tr class="sub"><th></th><th></th><th></th>'
        + "".join('<th class="subh">obj<br><span>Z1 / Z2 / Z3</span></th>' for _ in COLS)
        + '<th></th></tr></thead><tbody>'
        + "\n".join(trs) + '</tbody></table>')

    # ---- aggregate cards ----
    def card(k, label):
        return (f'<div class="kpi"><div class="n">{agg[k]["ok"]}/20</div>'
                f'<div class="l">{html.escape(label)} judge-OK</div></div>')
    cards = (card("b_old", "baseline 6/3") + card("b_new", "baseline 현재")
             + card("o_old", "ours 6/3") + card("o_new", "ours 현재"))

    tlO, tlN = sO.get("timelimit"), sN.get("timelimit")
    out = args.out or str(Path(args.new).parent / "compare_4way.html")
    Path(out).write_text(_html(table, cards, tlO, tlN), encoding="utf-8")
    print(f"[4way] {out}")
    return 0


def _fmt(v):
    return f"{v:,.0f}" if v is not None else "—"


def _cell(key, r, is_best):
    if r is None:
        return '<td class="miss">—</td>'
    obj = r.get("objective")
    z1, z2, z3 = r.get("obj1"), r.get("obj2"), r.get("obj3")
    zline = f'<span class="z">{_fmt(z1)} / {_fmt(z2)} / {_fmt(z3)}</span>'
    if key == "lb":
        return f'<td class="c lb"><b>{_fmt(obj)}</b><br>{zline}</td>'
    st = status(r)
    if st == "OK":
        cls = "c ok best" if is_best else "c ok"
        crown = ' 👑' if is_best else ''
        return f'<td class="{cls}"><b>{_fmt(obj)}</b>{crown}<br>{zline}</td>'
    if st == "DEADLINE":
        return (f'<td class="c dead"><b>{_fmt(obj)}</b> <span class="tag">시간초과</span>'
                f'<br>{zline}</td>')
    return '<td class="c inf">실현불가</td>'


def _html(table, cards, tlO, tlN):
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>OGC2026 — 4-way 비교 (baseline · 6/3 · 현재 · 수학적 최소)</title>
<style>
 body{{font-family:'Segoe UI','Malgun Gothic',system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1c2733}}
 header{{background:#16324f;color:#fff;padding:26px 36px}}
 header h1{{margin:0 0 6px;font-size:22px}} header p{{margin:0;opacity:.85;font-size:14px}}
 .wrap{{max-width:1280px;margin:0 auto;padding:22px 26px 80px}}
 .kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
 .kpi{{background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08);flex:1;min-width:130px}}
 .kpi .n{{font-size:26px;font-weight:700;color:#16324f}} .kpi .l{{color:#5a6b7b;font-size:12px}}
 .note{{background:#fff8e6;border-left:5px solid #e0a800;padding:12px 16px;border-radius:6px;font-size:13.5px;margin:12px 0}}
 .legend{{font-size:12.5px;color:#5a6b7b;margin:8px 0 4px}}
 table{{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 th,td{{padding:7px 8px;text-align:center;border-bottom:1px solid #eef1f4}}
 thead th{{background:#16324f;color:#fff;position:sticky;top:0}}
 thead th.lb{{background:#4a3f86}} thead th.base{{background:#33536f}} thead th.ours{{background:#1f6b43}}
 tr.sub th{{background:#24405c;font-weight:500;font-size:10.5px;padding:3px 6px}}
 tr.sub th span{{color:#aebfcf;font-size:9.5px}}
 td.inst{{font-weight:700;text-align:left}} td.nb,td.wts{{color:#5a6b7b;font-size:11px}}
 td.c b{{font-size:13px}}
 td.lb{{background:#f3f1fb;color:#4a3f86}}
 td.ok{{color:#16324f}} td.ok.best{{background:#e6f6ec;color:#1f6b43;font-weight:700}}
 td.dead{{color:#9a6b00;background:#fff6e0}} td.inf{{color:{RED};background:#fdecea;font-weight:600}}
 td.miss{{color:#bbb}}
 .z{{color:#8a97a4;font-size:10px}} .tag{{font-size:9px;background:#e0a800;color:#fff;padding:1px 4px;border-radius:4px}}
 td.delta .d{{font-weight:700;font-size:12px;padding:2px 6px;border-radius:5px}}
 .d.up{{background:#fdecea;color:{RED}}} .d.down{{background:#e6f6ec;color:{GREEN}}}
 .d.flat{{color:#9aa0a6}} .d.chg{{background:#fff6e0;color:#9a6b00;font-size:10px}}
 .foot{{font-size:12px;color:#5a6b7b;margin-top:18px;line-height:1.7}}
 code{{background:#eef1f4;padding:1px 5px;border-radius:4px}}
</style></head><body>
<header><h1>OGC 2026 — 4-way 비교: baseline · 6/3 알고리즘 · 현재 알고리즘 · 수학적 최소(LB)</h1>
<p>각 셀 = 가중 목적함수(obj) + 성분 Z1 / Z2 / Z3  (= t1 tardiness · t2 imbalance · t3 preference) · timelimit {tlO}/{tlN}s</p></header>
<div class="wrap">
 <div class="kpis">{cards}</div>
 <div class="note"><b>읽는 법:</b> 한 행에서 <b>👑/초록</b> = 4개 실솔버(baseline·ours 두 버전) 중 목적함수 최소(judge-OK 한정).
  <b>수학적 최소 LB</b>는 참조선(이론 하한) — 항상 최소지만 도달 불가능에 가까움. 맨 오른쪽 = ours <b>6/3→현재</b> 변화율
  (<span style="color:{RED}">+빨강=악화</span> / <span style="color:{GREEN}">−초록=개선</span>).</div>
 <div class="note"><b>LB = 0인 이유:</b> 20개 전부 모든 블록이 <code>release+processing ≤ due</code> → 완화상 불가피 지연 0,
  Z2·Z3 하한도 0이라 <b>이론 하한 = 0</b>. 즉 목적값 전부가 공간·크레인 혼잡 비용. 양수의 tight 하한은 CP/MIP 완화 필요.</div>
 <div class="note"><b>baseline이 두 번 나오는 이유:</b> 공식 greedy도 시간민감 → run마다 값이 흔들림(±20× 비결정성).
  ours 12개는 두 run에서 bit-identical이라, ours의 6/3→현재 차이는 <b>코드 변경(6/4 P2·P3)</b> 효과로 해석됨.</div>
 {table}
 <div class="foot">
  · <b>Z1</b>=Σ tardiness, <b>Z2</b>=workload imbalance(floor), <b>Z3</b>=preference penalty. 목적함수 = w1·Z1 + w2·Z2 + w3·Z3.<br>
  · <b>시간초과</b>: feasible 해를 찾았으나 로컬 timelimit 초과(대회 실서버 한도는 더 넉넉). <b>실현불가</b>: 유효 해 없음.<br>
  · LB는 인스턴스에만 의존하므로 두 run에서 동일. 데이터: 6/3 = compare_HONEST_seq_tl60, 현재 = compare_current_20260604.
 </div>
</div></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
