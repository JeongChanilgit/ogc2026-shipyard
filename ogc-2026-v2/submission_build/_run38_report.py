"""_run38_report.py [PROB] -- parse _run<PROB>_detailed.json + _run<PROB>_full.log into
a step-by-step timeline (stage durations + objective drops) and a postproc per-pass
table; emit a self-contained HTML (convergence chart + tables) + markdown to stdout.
"""
import os, sys, json, re

SB = os.path.dirname(os.path.abspath(__file__))
PROB = int(sys.argv[1]) if len(sys.argv) > 1 else 38
TAG = sys.argv[2] if len(sys.argv) > 2 else ""   # "" or "noorig"
_t = f"_{TAG}" if TAG else ""
JS = os.path.join(SB, f"_run{PROB}{_t}_detailed.json")
LOG = os.path.join(SB, f"_run{PROB}{_t}_full.log")
HTML = os.path.join(SB, "docs", f"prob{PROB}{_t}-step-timeline-2026-06-25.html")

rec = json.load(open(JS, encoding="utf-8"))
txt = open(LOG, encoding="utf-8").read()

sp = re.compile(r"\[PASS\] (\S+?)-pass bay=(\d+) n=(\d+) wall=\s*([\d.]+)s dobj=\s*([-\d,]+) acc=(\w+)")
mv = re.compile(r"\[PASS\] moveall blk=(\d+) (\d+)->(\d+) dobj=\s*([-\d,]+) acc=(\w+)")
passes = []
for line in txt.splitlines():
    m = sp.search(line)
    if m:
        passes.append(dict(type=m.group(1), bay=int(m.group(2)), n=int(m.group(3)),
                           wall=float(m.group(4)), dobj=int(m.group(5).replace(",", "")),
                           acc=m.group(6) == "True"))
        continue
    m = mv.search(line)
    if m:
        passes.append(dict(type="moveall", bay=int(m.group(3)), n=None, wall=None,
                           dobj=int(m.group(4).replace(",", "")), acc=m.group(5) == "True"))

stages = rec["stages"]


def fnum(x):
    return f"{x:,.0f}" if isinstance(x, (int, float)) else "-"


def fwall(x):
    return f"{x:.1f}s" if isinstance(x, (int, float)) else "-"


# convergence points = BEST-obj-so-far (best-of discards a worse orig) + accepted passes
pts, _bsf = [], None
for s in stages:
    if s["obj"] is None:
        continue
    _bsf = s["obj"] if _bsf is None else min(_bsf, s["obj"])
    pts.append((s["elapsed"], _bsf, s["stage"]))
pp_start = next((s["elapsed"] - s["dur"] for s in stages if s["stage"].startswith("3_")), None)
base = rec.get("postproc_base_obj")
cum_t, cur, pp_pts = 0.0, base, []
for p in passes:
    if p["wall"]:
        cum_t += p["wall"]
    if p["acc"] and cur is not None:
        cur -= p["dobj"]
        if pp_start is not None:
            pp_pts.append((pp_start + cum_t, cur))

# ---------- markdown ----------
W = rec["weights"]
print(f"# prob_{PROB} @ TL={rec['tl']:.0f}s — step timeline (cap30bl)")
print(f"w1={W['w1']:,} w2={W['w2']} w3={W['w3']}  ·  total wall={rec['total_wall']:.0f}s  "
      f"·  FINAL obj={fnum(rec['final_obj'])}\n")
print("## Stage timeline")
print(f"{'stage':<16}{'dur(s)':>9}{'elapsed':>9}{'obj':>15}{'z1':>9}{'z3':>8}{'Δobj':>15}  note")
prev = None
for s in stages:
    d = (prev - s["obj"]) if (prev is not None and s["obj"] is not None) else None
    print(f"{s['stage']:<16}{s['dur']:>9.1f}{s['elapsed']:>9.1f}{fnum(s['obj']):>15}"
          f"{str(s['z1']):>9}{str(s['z3']):>8}{fnum(d):>15}  {s.get('note','')}")
    if s["obj"] is not None:
        prev = s["obj"]
acc = [p for p in passes if p["acc"]]
spw = sum(p["wall"] for p in passes if p["wall"])
print(f"\n## Postproc passes: {len(passes)} total, {len(acc)} accepted, "
      f"spatial-wall sum={spw:.0f}s, total Δobj={fnum(sum(p['dobj'] for p in acc))}")
print(f"{'#':>3} {'type':>8} {'bay':>4} {'n':>5} {'wall':>7} {'Δobj':>14} {'acc':>5}")
for i, p in enumerate(passes):
    print(f"{i+1:>3} {p['type']:>8} {str(p['bay']):>4} {str(p['n'] or '-'):>5} "
          f"{fwall(p['wall']):>7} {fnum(p['dobj']):>14} {str(p['acc']):>5}")


# ---------- HTML ----------
def svg_chart(points, w=900, h=320, pad=64):
    if len(points) < 2:
        return "<p>insufficient points</p>"
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    x1 = x1 + 1 if x1 == x0 else x1
    y1 = y1 + 1 if y1 == y0 else y1

    def X(v):
        return pad + (v - x0) / (x1 - x0) * (w - 2 * pad)

    def Y(v):
        return h - pad - (v - y0) / (y1 - y0) * (h - 2 * pad)
    pl = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y, *_ in points)
    dots = "".join(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="#58a6ff"/>'
                   for x, y, *_ in points)
    labs = "".join(
        f'<text x="{X(p[0]):.1f}" y="{Y(p[1])-9:.1f}" fill="#8b949e" font-size="10" '
        f'text-anchor="middle">{p[2]}</text>' for p in points if len(p) > 2)
    ax = (f'<line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" stroke="#30363d"/>'
          f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h-pad}" stroke="#30363d"/>'
          f'<text x="{w/2}" y="{h-14}" fill="#8b949e" font-size="11" text-anchor="middle">'
          f'elapsed (s): {x0:.0f} → {x1:.0f}</text>'
          f'<text x="18" y="{h/2}" fill="#8b949e" font-size="11" '
          f'transform="rotate(-90 18 {h/2})" text-anchor="middle">obj: {y1:,.0f} → {y0:,.0f}</text>')
    return (f'<svg width="{w}" height="{h}" style="background:#0d1117;border:1px solid #30363d;'
            f'border-radius:8px"><rect/>{ax}<polyline points="{pl}" fill="none" '
            f'stroke="#58a6ff" stroke-width="2"/>{dots}{labs}</svg>')


full = sorted(pts + pp_pts)
rows_stage = "".join(
    f"<tr><td>{s['stage']}</td><td>{s['dur']:.1f}</td><td>{s['elapsed']:.1f}</td>"
    f"<td>{fnum(s['obj'])}</td><td>{s['z1']}</td><td>{s['z3']}</td><td>{s.get('note','')}</td></tr>"
    for s in stages)
rows_pass = "".join(
    f"<tr class='{'a' if p['acc'] else 'r'}'><td>{i+1}</td><td>{p['type']}</td>"
    f"<td>{p['bay']}</td><td>{p['n'] or '-'}</td><td>{fwall(p['wall'])}</td>"
    f"<td>{fnum(p['dobj'])}</td><td>{p['acc']}</td></tr>"
    for i, p in enumerate(passes))

html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>prob_{PROB} step timeline (cap30bl)</title><style>
body{{background:#0d1117;color:#e6edf3;font:14px/1.6 -apple-system,Segoe UI,sans-serif;margin:0;padding:28px}}
.wrap{{max-width:980px;margin:0 auto}}h1{{font-size:22px}}h2{{font-size:17px;border-bottom:1px solid #30363d;padding-bottom:5px;margin-top:28px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0}}th,td{{border:1px solid #30363d;padding:4px 8px;text-align:right}}
th{{background:#1f2630}}td:first-child,td:nth-child(2){{text-align:left}}tr.r td{{color:#6e7681}}tr.a td{{color:#3fb950}}
.k{{display:flex;gap:14px;flex-wrap:wrap;margin:12px 0}}.k>div{{background:#1f2630;border:1px solid #30363d;border-radius:8px;padding:10px 14px;text-align:center}}
.k .l{{color:#8b949e;font-size:11px}}.k .v{{font-size:20px;font-weight:700}}code{{background:#1f2630;padding:1px 6px;border-radius:4px}}
</style></head><body><div class="wrap">
<h1>prob_{PROB} @ TL={rec['tl']:.0f}s — 스텝별 시간·obj 감소 (cap30bl)</h1>
<p style="color:#8b949e">w1={W['w1']:,} w2={W['w2']} w3={W['w3']} · 채택 <code>OGC_PP_ACTIVE_CAP=30 + OGC_PP_BLPROBE=3</code></p>
<div class="k">
<div><div class="l">total wall</div><div class="v">{rec['total_wall']:.0f}s</div></div>
<div><div class="l">FINAL obj</div><div class="v">{fnum(rec['final_obj'])}</div></div>
<div><div class="l">postproc budget</div><div class="v">{rec.get('postproc_budget',0):.0f}s</div></div>
<div><div class="l">postproc 패스</div><div class="v">{len(acc)}/{len(passes)}</div></div>
</div>
<h2>수렴 곡선 (best obj vs elapsed)</h2>
{svg_chart(full)}
<h2>스테이지 타임라인</h2>
<table><tr><th>stage</th><th>dur(s)</th><th>elapsed(s)</th><th>obj</th><th>z1</th><th>z3</th><th>note</th></tr>{rows_stage}</table>
<h2>Postproc 패스별 ({len(passes)}개, {len(acc)} 수락, 총 Δobj={fnum(sum(p['dobj'] for p in acc))})</h2>
<p style="color:#8b949e">spatial 패스만 wall 기록(moveall/cross-bay은 PASSLOG 시간 미기록). 초록=수락.</p>
<table><tr><th>#</th><th>type</th><th>bay</th><th>n</th><th>wall</th><th>Δobj</th><th>acc</th></tr>{rows_pass}</table>
</div></body></html>"""
os.makedirs(os.path.dirname(HTML), exist_ok=True)
open(HTML, "w", encoding="utf-8").write(html)
print(f"\n-> HTML: {HTML}")
