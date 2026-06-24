"""_v5_traj_chart.py traj.json [out.html] -- chart per-step objective trajectory."""
import sys, os, json

src = sys.argv[1] if len(sys.argv) > 1 else "C:/claude-develop/OGC2026/submissions/v5_traj_prob_38.json"
out = sys.argv[2] if len(sys.argv) > 2 else "C:/claude-develop/OGC2026/ogc-2026-v2/docs/v5-traj.html"

d = json.load(open(src, encoding="utf-8"))
traj = d["traj"]
labels = [r["step"] for r in traj]
objs = [r["obj"] for r in traj]
z1s = [r["z1"] for r in traj]
z3s = [r["z3"] for r in traj]
ts = [r["t"] for r in traj]

rows = ""
prev = None
for k, r in enumerate(traj):
    o = r["obj"]
    delta = "" if (prev is None or o is None or prev is None) else f"{o-prev:+,.0f}"
    pct = "" if (prev in (None, 0) or o is None) else f"{(o-prev)/prev*100:+.1f}%"
    cls = "good" if (prev is not None and o is not None and o < prev) else ("bad" if (prev is not None and o is not None and o > prev) else "")
    rows += (f"<tr><td class='l'>{r['step']}</td><td>{'' if o is None else f'{o:,.0f}'}</td>"
             f"<td class='{cls}'>{delta}</td><td class='{cls}'>{pct}</td>"
             f"<td>{r['z1']}</td><td>{r['z2']}</td><td>{r['z3']}</td><td>{r['t']}s</td></tr>")
    if o is not None:
        prev = o

html = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>v5 step별 목적함수 궤적 — """ + str(d.get("inst", "")) + """</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
 body{margin:0;background:#0d0f13;color:#e8ebf1;font:14px/1.5 Segoe UI,sans-serif}
 .wrap{max-width:1100px;margin:0 auto;padding:24px}
 h1{font-size:20px} .sub{color:#969eae;margin-bottom:14px}
 #plot{height:420px} table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums;margin-top:16px}
 th,td{padding:5px 9px;text-align:right;border-bottom:1px solid #262b35}
 th{color:#969eae} td.l,th.l{text-align:left} .good{color:#7ee787} .bad{color:#ff6b6b} b{color:#5ad1c7}
</style></head><body><div class="wrap">
<h1>v5 step별 목적함수 궤적 — <b>""" + str(d.get("inst", "")) + """</b></h1>
<div class="sub">best=""" + (f"{d.get('best'):,.0f}" if d.get("best") else "-") + """ · rounds=""" + str(d.get("rounds", "")) + """ · STEP3=tardy greedy재배치(obj 일시 상승 가능) → STEP2=xyot CP-SAT 정제(obj 감소)</div>
<div id="plot"></div>
<table><thead><tr><th class="l">step</th><th>obj</th><th>Δ</th><th>Δ%</th><th>z1</th><th>z2</th><th>z3</th><th>t</th></tr></thead>
<tbody>""" + rows + """</tbody></table>
</div>
<script>
const L=""" + json.dumps(labels) + """, O=""" + json.dumps(objs) + """, Z1=""" + json.dumps(z1s) + """, Z3=""" + json.dumps(z3s) + """, T=""" + json.dumps(ts) + """;
const xi=L.map((_,i)=>i);
Plotly.newPlot('plot',[
 {x:xi,y:O,mode:'lines+markers',name:'obj',line:{color:'#5ad1c7',width:2},
  text:L.map((l,i)=>l+'  t='+T[i]+'s'),hovertemplate:'%{text}<br>obj=%{y:,.0f}<extra></extra>'},
 {x:xi,y:Z1,mode:'lines',name:'z1(tardy)',yaxis:'y2',line:{color:'#ff6b6b',width:1,dash:'dot'}},
],{paper_bgcolor:'#0d0f13',plot_bgcolor:'#0d0f13',font:{color:'#cfd6e2'},
   margin:{l:70,r:60,t:10,b:80},
   xaxis:{tickmode:'array',tickvals:xi,ticktext:L,tickangle:-40,gridcolor:'#1c2128'},
   yaxis:{title:'obj',type:'log',gridcolor:'#1c2128'},
   yaxis2:{title:'z1',overlaying:'y',side:'right',showgrid:false},
   legend:{x:0.8,y:1}});
</script></body></html>"""
open(out, "w", encoding="utf-8").write(html)
print("wrote", out)
