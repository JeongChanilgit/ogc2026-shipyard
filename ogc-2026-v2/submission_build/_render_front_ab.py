"""_render_front_ab.py inst  -- compare no-front (A) vs +frontmove (B), same fixed
start + same TL.  Tests the hypothesis: frontmove's value is NOT its own Δobj but
RAISING the other passes' realised Δobj (structure shake).  So the table shows, per
step, A's Δobj vs B's Δobj.  Opens HTML.
"""
import os, sys, json

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
BASE = "C:/claude-develop/OGC2026"
ORDER = ["puret", "moveall", "frontmoveall", "x-area", "x-time", "y-area", "y-time",
         "o-area", "spatial:x", "spatial:y", "spatial:o", "move", "swap"]
LABEL = {"puret": "순수-t", "moveall": "C3 cross-bay", "frontmoveall": "C3-front(선행이동)",
         "x-area": "x-area(면적)", "x-time": "x-time(시간)", "y-area": "y-area",
         "y-time": "y-time", "o-area": "o-area", "move": "z3 move", "swap": "z3 swap",
         "spatial:x": "spatial:x", "spatial:y": "spatial:y", "spatial:o": "spatial:o"}


def agg(steps):
    a = {}
    for s in steps:
        d = a.setdefault(s["step"], {"calls": 0, "acc": 0, "dobj": 0.0, "dt": 0.0})
        d["calls"] += 1; d["acc"] += 1 if s["accepted"] else 0
        d["dobj"] += s["d_obj"]; d["dt"] += s["dt"]
    return a


def load(name):
    p = os.path.join(V2, "out", name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def main(inst="38"):
    A = load(f"brief{inst}_nofront.json")
    B = load(f"brief{inst}_front.json")
    if not A or not B:
        print(f"prob_{inst}: missing", "nofront" if not A else "", "front" if not B else "")
        return None
    aA, aB = agg(A["steps"]), agg(B["steps"])
    dobjA = sum(x["dobj"] for x in aA.values()); dobjB = sum(x["dobj"] for x in aB.values())
    # "other steps" = everything except frontmoveall (front's indirect boost target)
    otherA = dobjA
    otherB = dobjB - aB.get("frontmoveall", {}).get("dobj", 0)
    front_own = aB.get("frontmoveall", {}).get("dobj", 0)
    objA, objB = float(A["objective"]), float(B["objective"])
    better = objB < objA
    PN = A.get("instance", f"prob_{inst}")

    rows = ""
    for k in [x for x in ORDER if (x in aA or x in aB)]:
        ca = aA.get(k, {"calls": 0, "acc": 0, "dobj": 0})
        cb = aB.get(k, {"calls": 0, "acc": 0, "dobj": 0})
        boost = cb["dobj"] - ca["dobj"]
        bcol = "#6ee7a0" if boost > 1 else ("#e0734d" if boost < -1 else "#7e8aa3")
        hot = ' style="background:#13241c"' if k == "frontmoveall" else ""
        rows += (f'<tr{hot}><td>{LABEL.get(k,k)}</td>'
                 f'<td class="r">{ca["calls"]}/{ca["acc"]}</td><td class="r">{ca["dobj"]:,.0f}</td>'
                 f'<td class="r" style="border-left:1px solid #2a3a5a">{cb["calls"]}/{cb["acc"]}</td>'
                 f'<td class="r">{cb["dobj"]:,.0f}</td>'
                 f'<td class="r" style="color:{bcol};font-weight:700">{boost:+,.0f}</td></tr>')

    def hrow(m, va, vb, fmt="{:,.0f}", low=True):
        wa = (va < vb) if low else (va > vb)
        return (f'<tr><td>{m}</td><td class="r"{" class=b" if wa else ""}>{fmt.format(va)}</td>'
                f'<td class="r"{"" if wa else " class=b"} style="border-left:1px solid #2a3a5a">{fmt.format(vb)}</td></tr>')

    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{PN} frontmove A/B</title><style>
 body{{background:#0d1320;color:#d6deee;font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:32px}}
 .wrap{{max-width:980px;margin:0 auto}} h1{{font-size:22px;margin:0 0 4px}}
 h2{{font-size:16px;color:#9fb0cc;margin:24px 0 10px;border-bottom:1px solid #23304a;padding-bottom:6px}}
 .sub{{color:#7e8aa3;margin-bottom:14px}} table{{width:100%;border-collapse:collapse}}
 th,td{{padding:7px 10px;border-bottom:1px solid #1c2740;text-align:left}}
 th{{color:#7e8aa3;font-size:12px}} td.r{{text-align:right;font-variant-numeric:tabular-nums}}
 .b,td.b{{font-weight:700;color:#36d17a}}
 .panel{{background:#141d2e;border:1px solid #23304a;border-radius:10px;padding:16px}}
 .verdict{{border-radius:10px;padding:14px 18px;margin:12px 0;font-size:15px}}
 .win{{background:#13241c;border:1px solid #2c5}} .lose{{background:#241616;border:1px solid #a44}}
 .verdict b{{font-size:18px}} code{{background:#1c2740;padding:1px 6px;border-radius:4px;color:#9fd}}
</style></head><body><div class="wrap">
<h1>{PN} — frontmove A/B (루프 구조, 같은 고정 초기해)</h1>
<div class="sub">A = no-front · B = +frontmove(K16·ts4·bud50, 라운드 끝) · 통합(순수-t+moveall+듀얼윈도우+move/swap) · TL={A['tl']:.0f}s · 고정 v2 출발해</div>

<div class="verdict {'win' if better else 'lose'}">
{'✓' if better else '✗'} +frontmove 최종 obj = <b>{objB:,.0f}</b> vs no-front <b>{objA:,.0f}</b>
({'−' if better else '+'}{abs(objA-objB):,.0f} {'개선' if better else '악화'}).
가설검증 → frontmove 자체 Δ={front_own:,.0f}; <b>다른 스텝 합계 Δ: A {otherA:,.0f} → B {otherB:,.0f}</b>
({'+' if otherB>otherA else ''}{otherB-otherA:,.0f} = front가 {'키움(가설 ✓)' if otherB>otherA else '못 키움'}).
</div>

<h2>요약</h2>
<div class="panel"><table>
<tr><th>지표</th><th class="r">A: no-front</th><th class="r" style="border-left:1px solid #2a3a5a">B: +frontmove</th></tr>
{hrow("최종 obj", objA, objB)}
{hrow("z1", float(A['z1']), float(B['z1']))}
{hrow("z3", float(A['z3']), float(B['z3']))}
{hrow("후처리 총 Δobj", dobjA, dobjB, low=False)}
{hrow("다른 스텝 Δobj(front 제외)", otherA, otherB, low=False)}
{hrow("스텝 수", float(len(A['steps'])), float(len(B['steps'])), low=False)}
</table></div>

<h2>스텝별 Δobj — A vs B (가설: B의 다른 스텝이 더 큰가?)</h2>
<div class="panel"><table>
<tr><th>스텝</th><th class="r">A 호출/채택</th><th class="r">A Δobj</th>
<th class="r" style="border-left:1px solid #2a3a5a">B 호출/채택</th><th class="r">B Δobj</th><th class="r">B−A boost</th></tr>
{rows}
</table></div>
<p class="sub" style="margin-top:18px">boost &gt; 0(초록) = frontmove가 그 스텝의 실현 Δobj를 키움(구조 흔들기 효과). 빨강 = 줄임(시간 강탈).</p>
<p class="sub">생성: <code>_batch_front.py</code> → <code>brief{inst}_nofront/front.json</code> → <code>_render_front_ab.py</code>.</p>
</div></body></html>"""
    outp = os.path.join(BASE, "docs", f"front-ab-{inst}.html")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    open(outp, "w", encoding="utf-8").write(html)
    print("wrote", outp, "| better:", better, "| other-boost:", round(otherB - otherA))
    return outp


if __name__ == "__main__":
    inst = sys.argv[1] if len(sys.argv) > 1 else "38"
    p = main(inst)
    if p and os.name == "nt" and "--no-open" not in sys.argv:
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", p], shell=False)
