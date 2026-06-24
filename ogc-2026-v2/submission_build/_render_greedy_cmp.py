"""_render_greedy_cmp.py -- compare two starting solutions (z3-only greedy W1=0 vs
z1z3 greedy W1=1.0), both polished by the dual-window v3 postproc, into one HTML:
head-to-head + per-step Δobj + per-call detail for each.  Opens in browser.
"""
import os, sys, json

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
BASE = "C:/claude-develop/OGC2026"
ORDER = ["puret", "moveall", "frontmoveall", "x-area", "x-time", "y-area", "y-time",
         "o-area", "spatial:x", "spatial:y", "spatial:o", "move", "swap"]
LABEL = {"puret": "순수-t", "moveall": "C3 cross-bay", "frontmoveall": "C3-front(선행이동)",
         "x-area": "x-area(면적인접)", "x-time": "x-time(시간인접)", "y-area": "y-area",
         "y-time": "y-time", "o-area": "o-area", "move": "z3 move", "swap": "z3 swap",
         "spatial:x": "spatial:x", "spatial:y": "spatial:y", "spatial:o": "spatial:o"}
COL = {"x-area": "#5aa0e0", "x-time": "#7b6ee0", "y-area": "#4fb0c0", "y-time": "#c08ae0",
       "o-area": "#e07ba0", "puret": "#6ee7a0", "moveall": "#e0b34d",
       "frontmoveall": "#e0734d", "move": "#9fb0cc", "swap": "#5a6a86"}


def agg(steps):
    a = {}
    for s in steps:
        d = a.setdefault(s["step"], {"calls": 0, "acc": 0, "dt": 0.0, "dobj": 0.0})
        d["calls"] += 1; d["acc"] += 1 if s["accepted"] else 0
        d["dt"] += s["dt"]; d["dobj"] += s["d_obj"]
    return a


def load(name):
    p = os.path.join(V2, "out", name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def percall(steps):
    rows = ""
    for i, s in enumerate(steps, 1):
        acc = s["accepted"]; oa = s.get("obj_after")
        oastr = f"{oa/1e6:.3f}M" if oa is not None else "—"
        rc = ' style="background:#13241c"' if acc else ""
        c = COL.get(s["step"], "#9fb0cc")
        rows += (f'<tr{rc}><td class="r">{i}</td><td><span style="color:{c}">&#9679;</span> {s["step"]}</td>'
                 f'<td class="r">{s["bay"]}</td><td class="r">{s["dt"]:.1f}</td>'
                 f'<td class="r b">{s["d_obj"]:,.0f}</td><td class="r">{oastr}</td>'
                 f'<td class="r">{"&#10003;" if acc else "&middot;"}</td></tr>')
    return (f'<div class="panel" style="max-height:460px;overflow:auto"><table>'
            f'<tr><th>#</th><th>스텝</th><th class="r">베이</th><th class="r">dt</th>'
            f'<th class="r">Δobj</th><th class="r">obj후</th><th class="r">채택</th></tr>'
            f'{rows}</table></div>')


def main(inst="38"):
    A = load(f"brief{inst}_z3only.json")   # W1=0
    B = load(f"brief{inst}_z1z3.json")     # W1=1.0
    if not A or not B:
        print(f"prob_{inst}: missing json(s):", "z3only" if not A else "", "z1z3" if not B else "")
        return None

    def row(metric, fa, fb, fmt="{:,.0f}", better="low"):
        va, vb = fa, fb
        if better == "low":
            win_a = va < vb
        else:
            win_a = va > vb
        sa = (' class="b"' if win_a else "")
        sb = (' class="b"' if not win_a else "")
        return (f'<tr><td>{metric}</td><td class="r"{sa}>{fmt.format(va)}</td>'
                f'<td class="r"{sb} style="border-left:1px solid #2a3a5a">{fmt.format(vb)}</td></tr>')

    aA, aB = agg(A["steps"]), agg(B["steps"])
    dobjA = sum(x["dobj"] for x in aA.values()); dobjB = sum(x["dobj"] for x in aB.values())
    mA, mB = A.get("mtrace", {}), B.get("mtrace", {})
    baseA = mA.get("base_obj") or mA.get("v2_obj") or 0
    baseB = mB.get("base_obj") or mB.get("v2_obj") or 0
    winner = "z3-only (W1=0)" if A["objective"] < B["objective"] else "z1z3 (W1=1.0)"
    gap = abs(A["objective"] - B["objective"])

    steprows = ""
    for k in [x for x in ORDER if (x in aA or x in aB)]:
        ca = aA.get(k, {"calls": 0, "acc": 0, "dobj": 0}); cb = aB.get(k, {"calls": 0, "acc": 0, "dobj": 0})
        steprows += (f'<tr><td>{LABEL.get(k,k)}</td>'
                     f'<td class="r">{ca["calls"]}/{ca["acc"]}</td><td class="r b">{ca["dobj"]:,.0f}</td>'
                     f'<td class="r" style="border-left:1px solid #2a3a5a">{cb["calls"]}/{cb["acc"]}</td>'
                     f'<td class="r b">{cb["dobj"]:,.0f}</td></tr>')

    PN = A.get("instance", f"prob_{inst}")
    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{PN} 출발해 비교 (z3-only vs z1z3)</title>
<style>
 body{{background:#0d1320;color:#d6deee;font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:32px}}
 .wrap{{max-width:1040px;margin:0 auto}} h1{{font-size:22px;margin:0 0 4px}}
 h2{{font-size:16px;color:#9fb0cc;margin:26px 0 10px;border-bottom:1px solid #23304a;padding-bottom:6px}}
 .sub{{color:#7e8aa3;margin-bottom:16px}}
 table{{width:100%;border-collapse:collapse}} th,td{{padding:7px 10px;border-bottom:1px solid #1c2740;text-align:left}}
 th{{color:#7e8aa3;font-size:12px}} td.r{{text-align:right;font-variant-numeric:tabular-nums}} td.b{{font-weight:700;color:#36d17a}}
 .panel{{background:#141d2e;border:1px solid #23304a;border-radius:10px;padding:16px}}
 .verdict{{background:#13241c;border:1px solid #2c5;border-radius:10px;padding:16px 20px;margin:12px 0;font-size:16px}}
 .verdict b{{color:#6ee7a0;font-size:19px}}
 .two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
 code{{background:#1c2740;padding:1px 6px;border-radius:4px;color:#9fd}}
</style></head><body><div class="wrap">
<h1>{PN} — 출발해 비교: z3-only vs z1z3 greedy</h1>
<div class="sub">둘 다 듀얼-윈도우(area+time) v3 후처리로 폴리시 · TL={A['tl']:.0f}s each · 듀얼윈도우 on · cap40</div>

<div class="verdict">승자: <b>{winner}</b> — 최종 obj가 {gap:,.0f} 더 낮음.
(z3-only는 배치가 선호베이로 몰려 z1↑ 출발, z1z3은 균형 출발. 후처리가 둘 다 z1을 깎은 뒤 최종 비교.)</div>

<h2>Head-to-head</h2>
<div class="panel"><table>
<tr><th>지표</th><th class="r">z3-only (W1=0)</th><th class="r" style="border-left:1px solid #2a3a5a">z1z3 (W1=1.0)</th></tr>
{row("v2 출발 obj (base)", baseA, baseB)}
{row("최종 obj", float(A["objective"]), float(B["objective"]))}
{row("z1", float(A["z1"]), float(B["z1"]))}
{row("z3", float(A["z3"]), float(B["z3"]))}
{row("후처리 총 Δobj", dobjA, dobjB, better="high")}
{row("스텝 수", float(len(A["steps"])), float(len(B["steps"])), better="high")}
</table></div>

<h2>스텝별 Δobj (호출/채택 · Δobj)</h2>
<div class="panel"><table>
<tr><th>스텝</th><th class="r">z3-only 호출/채택</th><th class="r">Δobj</th>
<th class="r" style="border-left:1px solid #2a3a5a">z1z3 호출/채택</th><th class="r">Δobj</th></tr>
{steprows}
</table></div>

<h2>콜 단위 상세 (전체 스텝)</h2>
<div class="two">
<div><div class="sub" style="margin:0 0 6px">z3-only (W1=0) — {len(A['steps'])} 콜</div>{percall(A['steps'])}</div>
<div><div class="sub" style="margin:0 0 6px">z1z3 (W1=1.0) — {len(B['steps'])} 콜</div>{percall(B['steps'])}</div>
</div>

<p class="sub" style="margin-top:22px">생성: <code>_brief38.py</code>(OGC_PLACE_W1_SCALE=0 / 1.0, OGC_PP_DUALWIN=1) → <code>out/brief38_z3only.json</code>,<code>out/brief38_z1z3.json</code> → <code>_render_greedy_cmp.py</code>.</p>
</div></body></html>"""

    outp = os.path.join(BASE, "docs", f"brief-greedy-cmp-{inst}.html")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    open(outp, "w", encoding="utf-8").write(html)
    print("wrote", outp, "| winner:", winner)
    return outp


if __name__ == "__main__":
    inst = sys.argv[1] if len(sys.argv) > 1 else "38"
    p = main(inst)
    if p and os.name == "nt" and "--no-open" not in sys.argv:
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", p], shell=False)
