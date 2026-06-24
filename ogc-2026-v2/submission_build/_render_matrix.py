"""_render_matrix.py inst  -- tabulate the frontmove x window config matrix.
Reads the 5 config jsons, shows obj/z1/z3/total-Δ/front(calls,acc,Δ)/other-Δ,
highlights the best obj.  Opens HTML.
"""
import os, sys, json

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
BASE = "C:/claude-develop/OGC2026"

# (label, filename-template)
ROWS = [
    ("no-front · dualwin",        "brief{i}_nofront.json"),
    ("front-LAST · dualwin",      "brief{i}_front.json"),
    ("front-FIRST · dualwin",     "brief{i}_c3_ffdual.json"),
    ("no-front · single-win",     "brief{i}_c4_nofront_single.json"),
    ("front-FIRST · single-win",  "brief{i}_c5_ffsingle.json"),
]


def load(name):
    p = os.path.join(V2, "out", name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def agg(steps):
    a = {}
    for s in steps:
        d = a.setdefault(s["step"], {"calls": 0, "acc": 0, "dobj": 0.0})
        d["calls"] += 1; d["acc"] += 1 if s["accepted"] else 0; d["dobj"] += s["d_obj"]
    return a


def main(inst="38"):
    data = []
    for label, tmpl in ROWS:
        d = load(tmpl.format(i=inst))
        if d:
            data.append((label, d))
    if not data:
        print("no matrix jsons found")
        return None
    best = min(d["objective"] for _l, d in data)

    trs = ""
    for label, d in data:
        a = agg(d["steps"])
        tot = sum(x["dobj"] for x in a.values())
        f = a.get("frontmoveall", {"calls": 0, "acc": 0, "dobj": 0})
        other = tot - f["dobj"]
        win = d["objective"] == best
        objcell = f'<td class="r b">{d["objective"]:,.0f} ★</td>' if win else f'<td class="r">{d["objective"]:,.0f}</td>'
        trs += (f'<tr><td>{label}</td>{objcell}'
                f'<td class="r">{d["z1"]:,.0f}</td><td class="r">{d["z3"]:,.0f}</td>'
                f'<td class="r">{tot:,.0f}</td>'
                f'<td class="r">{f["calls"]}/{f["acc"]} · {f["dobj"]:,.0f}</td>'
                f'<td class="r">{other:,.0f}</td><td class="r">{d["wall"]:.0f}s</td></tr>')

    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>prob_{inst} 아이디어 매트릭스</title><style>
 body{{background:#0d1320;color:#d6deee;font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:32px}}
 .wrap{{max-width:1000px;margin:0 auto}} h1{{font-size:22px;margin:0 0 4px}}
 .sub{{color:#7e8aa3;margin-bottom:16px}} table{{width:100%;border-collapse:collapse}}
 th,td{{padding:8px 10px;border-bottom:1px solid #1c2740;text-align:left}}
 th{{color:#7e8aa3;font-size:12px}} td.r{{text-align:right;font-variant-numeric:tabular-nums}}
 td.b{{font-weight:700;color:#36d17a}} .panel{{background:#141d2e;border:1px solid #23304a;border-radius:10px;padding:16px}}
 code{{background:#1c2740;padding:1px 6px;border-radius:4px;color:#9fd}}
</style></head><body><div class="wrap">
<h1>prob_{inst} — 아이디어 매트릭스 (frontmove × window, 15분, 고정 출발해)</h1>
<div class="sub">전부 같은 고정 v2 출발해 + 통합 후처리(순수-t·moveall·move/swap) · TL=900s · ★ = 최소 obj</div>
<div class="panel"><table>
<tr><th>config</th><th class="r">최종 obj</th><th class="r">z1</th><th class="r">z3</th>
<th class="r">후처리 Δobj</th><th class="r">front 콜/채택·Δ</th><th class="r">다른스텝 Δ</th><th class="r">wall</th></tr>
{trs}
</table></div>
<p class="sub" style="margin-top:16px">front-FIRST = frontmove를 라운드 맨 앞에서 먼저 흔들기(가설: 다른 패스가 그 위에 더 깎음).
single-win = 듀얼윈도우 끄고 단일 x/y/o(듀얼이 prob_38 포화 베이에서 중복이라 의심).</p>
<p class="sub">생성: <code>_batch_matrix.py</code> → <code>_render_matrix.py</code>.</p>
</div></body></html>"""
    outp = os.path.join(BASE, "docs", f"matrix-{inst}.html")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    open(outp, "w", encoding="utf-8").write(html)
    print("wrote", outp, "| best obj:", f"{best:,.0f}")
    return outp


if __name__ == "__main__":
    inst = sys.argv[1] if len(sys.argv) > 1 else "38"
    p = main(inst)
    if p and os.name == "nt" and "--no-open" not in sys.argv:
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", p], shell=False)
