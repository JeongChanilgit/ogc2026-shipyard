"""_render_brief38.py -- read out/brief38.json (primary, latest run) and, if present,
out/brief38_cap40.json (the earlier cap=40 run) and render a self-contained HTML
briefing: cap40 vs cap30 comparison + stage summary + per-step time/obj breakdown +
obj-vs-wall timeline.  Opens in the browser.
"""
import os, sys, json

SB = os.path.dirname(os.path.abspath(__file__)); V2 = os.path.dirname(SB)
BASE = "C:/claude-develop/OGC2026"

ORDER = ["puret", "moveall", "frontmoveall", "x-area", "x-time", "y-area", "y-time",
         "o-area", "spatial:x", "spatial:y", "spatial:o", "move", "swap"]
LABEL = {"puret": "순수-t", "moveall": "C3 cross-bay(all-fit)",
         "frontmoveall": "C3-front(선행블록 이동)", "x-area": "x-area(면적인접)",
         "x-time": "x-time(시간인접)", "y-area": "y-area", "y-time": "y-time", "o-area": "o-area",
         "spatial:x": "x축(+t,윈도)", "spatial:y": "y축(+t,윈도)",
         "spatial:o": "o축(+t,윈도)", "move": "z3 move(선호베이)", "swap": "z3 swap"}


def aggregate(steps):
    agg = {}
    for s in steps:
        a = agg.setdefault(s["step"], {"calls": 0, "acc": 0, "dt": 0.0, "dobj": 0.0})
        a["calls"] += 1; a["acc"] += 1 if s["accepted"] else 0
        a["dt"] += s["dt"]; a["dobj"] += s["d_obj"]
    return agg


def main():
    jp = os.path.join(V2, "out", "brief38.json")
    d = json.load(open(jp, encoding="utf-8"))
    steps = d["steps"]; mt = d.get("mtrace", {})
    agg = aggregate(steps)
    tot_dt = sum(a["dt"] for a in agg.values()) or 1.0
    tot_dobj = sum(a["dobj"] for a in agg.values())

    # optional comparison baseline (BRIEF_CMP env, default cap40 run)
    cmp_path = os.path.join(V2, "out", os.environ.get("BRIEF_CMP", "brief38_cap40.json"))
    cmp_html = ""
    if os.path.exists(cmp_path):
        c = json.load(open(cmp_path, encoding="utf-8"))
        cagg = aggregate(c["steps"])
        ctot_dobj = sum(a["dobj"] for a in cagg.values())
        ctot_dt = sum(a["dt"] for a in cagg.values())

        def _cfglab(j, dflt):
            cc = j.get("config")
            return (f"win={cc.get('window')}·cap{cc.get('ts_cap')}·{int(j.get('tl',0))//60}분" if cc else dflt)
        clab = _cfglab(c, "win=x·cap40·10분 (이전)")
        dlab = _cfglab(d, "이번")

        def cell(agg_, k, fld):
            return agg_.get(k, {}).get(fld, 0)
        rows = ""
        for k in [x for x in ORDER if (x in agg or x in cagg)]:
            rows += (f'<tr><td>{LABEL.get(k,k)}</td>'
                     f'<td class="r">{cell(cagg,k,"calls"):,} / {cell(cagg,k,"acc"):,}</td>'
                     f'<td class="r">{cell(cagg,k,"dt"):.0f}s</td>'
                     f'<td class="r">{cell(cagg,k,"dobj"):,.0f}</td>'
                     f'<td class="r" style="border-left:1px solid #2a3a5a">{cell(agg,k,"calls"):,} / {cell(agg,k,"acc"):,}</td>'
                     f'<td class="r">{cell(agg,k,"dt"):.0f}s</td>'
                     f'<td class="r b">{cell(agg,k,"dobj"):,.0f}</td></tr>')
        better = (d.get("objective") or 0) < (c.get("objective") or 0)
        cmp_html = f"""
<h2>이전 vs 이번 비교 ({clab} → {dlab})</h2>
<div class="panel">
<table>
<tr><th>지표</th><th class="r">{clab}</th><th class="r" style="border-left:1px solid #2a3a5a">{dlab}</th></tr>
<tr><td>최종 obj</td><td class="r">{(c.get('objective') or 0):,.0f}</td><td class="r b" style="border-left:1px solid #2a3a5a">{(d.get('objective') or 0):,.0f} {'✓ 개선' if better else '↑ 악화'}</td></tr>
<tr><td>후처리 총 Δobj</td><td class="r">{ctot_dobj:,.0f}</td><td class="r b" style="border-left:1px solid #2a3a5a">{tot_dobj:,.0f}</td></tr>
<tr><td>총 스텝 / 채택</td><td class="r">{len(c['steps']):,} / {sum(a['acc'] for a in cagg.values()):,}</td><td class="r" style="border-left:1px solid #2a3a5a">{len(steps):,} / {sum(a['acc'] for a in agg.values()):,}</td></tr>
<tr><td>z1 / z3</td><td class="r">{(c.get('z1') or 0):,.0f} / {(c.get('z3') or 0):,.0f}</td><td class="r" style="border-left:1px solid #2a3a5a">{(d.get('z1') or 0):,.0f} / {(d.get('z3') or 0):,.0f}</td></tr>
</table>
<div style="height:14px"></div>
<table>
<tr><th>스텝</th><th class="r">{clab} 호출/채택</th><th class="r">wall</th><th class="r">Δobj</th>
<th class="r" style="border-left:1px solid #2a3a5a">{dlab} 호출/채택</th><th class="r">wall</th><th class="r">Δobj</th></tr>
{rows}
</table>
</div>"""

    # timeline (uses obj_after when present, else reconstruct from d_obj)
    base_obj = mt.get("base_obj") or mt.get("v2_obj") or ((d.get("objective") or 0) + tot_dobj)
    pts = [(0.0, base_obj)]; cw = 0.0
    for s in steps:
        cw += s["dt"]
        oa = s.get("obj_after")
        y = oa if oa is not None else (pts[-1][1] - s["d_obj"])
        pts.append((cw, y))
    W, H, padL, padB, padT, padR = 920, 300, 90, 36, 16, 16
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    xmax = max(xs) or 1.0; ymin = min(ys); ymax = max(ys); yr = (ymax - ymin) or 1.0
    px = lambda x: padL + (x / xmax) * (W - padL - padR)
    py = lambda y: padT + (1 - (y - ymin) / yr) * (H - padT - padB)
    poly = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in pts)
    grid = ""
    for i in range(5):
        yv = ymin + yr * i / 4; yy = py(yv)
        grid += (f'<line x1="{padL}" y1="{yy:.1f}" x2="{W-padR}" y2="{yy:.1f}" stroke="#23304a"/>'
                 f'<text x="{padL-8}" y="{yy+4:.1f}" fill="#7e8aa3" font-size="11" text-anchor="end">{yv/1e6:.2f}M</text>')
    xticks = ""
    for i in range(7):
        xv = xmax * i / 6; xx = px(xv)
        xticks += (f'<line x1="{xx:.1f}" y1="{H-padB}" x2="{xx:.1f}" y2="{H-padB+4}" stroke="#3a4a66"/>'
                   f'<text x="{xx:.1f}" y="{H-padB+18}" fill="#7e8aa3" font-size="11" text-anchor="middle">{xv:.0f}s</text>')
    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">{grid}{xticks}'
           f'<polyline points="{poly}" fill="none" stroke="#36d17a" stroke-width="2"/>'
           f'<text x="{padL}" y="12" fill="#9fb0cc" font-size="11">obj (M) ← postproc wall(s) →</text></svg>')

    # per-step rows (cap30)
    rows = ""
    for k in [x for x in ORDER if agg.get(x, {}).get("calls")]:
        a = agg[k]; pct = a["dt"] / tot_dt * 100
        eff = a["dobj"] / a["dt"] if a["dt"] > 0.5 else 0
        hot = ' class="hot"' if k == "puret" else ""
        rows += (f'<tr{hot}><td>{LABEL.get(k,k)}</td><td class="r">{a["calls"]:,}</td>'
                 f'<td class="r">{a["acc"]:,}</td><td class="r">{a["dt"]:.1f}</td>'
                 f'<td class="r">{pct:.0f}%</td><td class="r b">{a["dobj"]:,.0f}</td>'
                 f'<td class="r">{eff:,.0f}</td></tr>')

    # per-call detail (all calls)
    STEP_COLOR = {"puret": "#6ee7a0", "moveall": "#e0b34d", "frontmoveall": "#e0734d",
                  "x-area": "#5aa0e0", "x-time": "#7b6ee0", "y-area": "#4fb0c0",
                  "y-time": "#c08ae0", "o-area": "#e07ba0", "spatial:x": "#5aa0e0",
                  "spatial:y": "#7b6ee0", "spatial:o": "#e07ba0", "move": "#9fb0cc",
                  "swap": "#5a6a86"}
    prc = ""
    for i, s in enumerate(steps, 1):
        acc = s["accepted"]; oa = s.get("obj_after")
        oastr = f"{oa/1e6:.3f}M" if oa is not None else "—"
        rowcls = ' style="background:#13241c"' if acc else ""
        col = STEP_COLOR.get(s["step"], "#9fb0cc")
        prc += (f'<tr{rowcls}><td class="r">{i}</td>'
                f'<td><span style="color:{col}">&#9679;</span> {s["step"]}</td>'
                f'<td class="r">{s["bay"]}</td><td class="r">{s["dt"]:.1f}</td>'
                f'<td class="r b">{s["d_obj"]:,.0f}</td><td class="r">{oastr}</td>'
                f'<td class="r">{"&#10003;" if acc else "&middot;"}</td></tr>')
    percall_html = f"""
<h2>콜 단위 상세 (전체 {len(steps):,} 콜 — 각 콜이 얼마 깎았나)</h2>
<div class="sub" style="margin:0 0 8px">채택된 콜만 obj가 내려갑니다(never-worse). 녹색 행 = 채택. 스크롤.</div>
<div class="panel" style="max-height:520px;overflow:auto">
<table>
<tr><th>#</th><th>스텝</th><th class="r">베이</th><th class="r">dt(s)</th><th class="r">Δobj</th><th class="r">obj후</th><th class="r">채택</th></tr>
{prc}
</table></div>"""

    z = lambda k: (d.get(k) if d.get(k) is not None else 0)
    pur = agg.get("puret", {"dobj": 0, "acc": 0, "dt": 0, "calls": 0})
    pur_share = (pur["dobj"] / tot_dobj * 100) if tot_dobj else 0
    cfg = d.get("config", {})

    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>prob_38 순수-t / cap30 브리핑</title>
<style>
 body{{background:#0d1320;color:#d6deee;font:14px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:32px}}
 .wrap{{max-width:980px;margin:0 auto}} h1{{font-size:22px;margin:0 0 4px}}
 h2{{font-size:16px;color:#9fb0cc;margin:28px 0 10px;border-bottom:1px solid #23304a;padding-bottom:6px}}
 .sub{{color:#7e8aa3;margin-bottom:20px}}
 .cards{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}}
 .card{{background:#141d2e;border:1px solid #23304a;border-radius:10px;padding:12px 16px;min-width:120px}}
 .card .k{{color:#7e8aa3;font-size:12px}} .card .v{{font-size:20px;font-weight:700;margin-top:2px}}
 table{{width:100%;border-collapse:collapse;margin-top:8px}}
 th,td{{padding:7px 10px;border-bottom:1px solid #1c2740;text-align:left}}
 th{{color:#7e8aa3;font-size:12px;font-weight:600}}
 td.r{{text-align:right;font-variant-numeric:tabular-nums}} td.b{{font-weight:700;color:#36d17a}}
 tr.hot td{{background:#13241c}} tr.hot td:first-child{{color:#6ee7a0;font-weight:700}}
 .panel{{background:#141d2e;border:1px solid #23304a;border-radius:10px;padding:18px}}
 .note{{background:#15203a;border-left:3px solid #3a7bd5;padding:10px 14px;border-radius:6px;margin:10px 0;color:#bcd}}
 .big{{color:#6ee7a0;font-weight:700}} code{{background:#1c2740;padding:1px 6px;border-radius:4px;color:#9fd}}
</style></head><body><div class="wrap">
<h1>prob_38 — 순수-t + 윈도우({cfg.get('window','x')}) 스텝별 브리핑</h1>
<div class="sub">v2(@scale0.5) + v3 후처리 · 윈도우=<b>{cfg.get('window','x')}</b> (tmargin={cfg.get('tmargin','0')}) · per-pass cap={cfg.get('ts_cap','40')}s · TL={d['tl']:.0f}s · 실제 wall {d['wall']:.0f}s · 단일-scale(클린 계측)</div>

<div class="cards">
 <div class="card"><div class="k">최종 obj</div><div class="v">{z('objective'):,.0f}</div></div>
 <div class="card"><div class="k">z1</div><div class="v">{z('z1'):,.0f}</div></div>
 <div class="card"><div class="k">z2</div><div class="v">{z('z2'):,.0f}</div></div>
 <div class="card"><div class="k">z3</div><div class="v">{z('z3'):,.0f}</div></div>
 <div class="card"><div class="k">feasible</div><div class="v">{'✓' if d['feasible'] else '✗ −1'}</div></div>
</div>
{cmp_html}

<h2>스텝별 시간·Δobj (cap30: 각 스텝이 얼마 깎고 얼마 먹나)</h2>
<div class="panel">
<table>
<tr><th>스텝</th><th class="r">호출</th><th class="r">채택</th><th class="r">총 wall</th><th class="r">wall%</th><th class="r">총 Δobj</th><th class="r">효율(Δobj/s)</th></tr>
{rows}
<tr style="border-top:2px solid #2a3a5a"><td><b>합계</b></td><td class="r">{sum(a['calls'] for a in agg.values()):,}</td><td class="r">{sum(a['acc'] for a in agg.values()):,}</td><td class="r">{tot_dt:.1f}</td><td class="r">100%</td><td class="r b">{tot_dobj:,.0f}</td><td class="r"></td></tr>
</table>
</div>

<div class="note">
<b>순수-t (NEW) 기여 (cap30):</b> 호출 {pur['calls']:,}회 · 채택 {pur['acc']:,}회 · wall {pur['dt']:.1f}s ·
Δobj <span class="big">{pur['dobj']:,.0f}</span> (후처리 총 개선의 <span class="big">{pur_share:.0f}%</span>).
</div>

<h2>후처리 obj 추이 (wall 대비)</h2>
<div class="panel">{svg}</div>
{percall_html}

<p class="sub" style="margin-top:24px">생성: <code>_brief38.py</code>(OGC_PP_TS_CAP=30) → <code>out/brief38.json</code> → <code>_render_brief38.py</code>.
이전 cap40 = <code>out/brief38_cap40.json</code>.</p>
</div></body></html>"""

    outp = os.path.join(BASE, "docs", "brief-puret-38.html")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    open(outp, "w", encoding="utf-8").write(html)
    print("wrote", outp)
    return outp


if __name__ == "__main__":
    p = main()
    if os.name == "nt":
        import subprocess
        subprocess.Popen(["cmd", "/c", "start", "", p], shell=False)
