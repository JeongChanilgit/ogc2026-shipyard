"""_v5_3d.py -- build a 3D comparison HTML (v5 vs current) from saved _v5_res
solutions, using the existing 3D tool (dump_geom3d.geom_from_sol)."""
import sys, os, json

V5 = os.path.dirname(os.path.abspath(__file__))
SB = r"C:/claude-develop/OGC2026/ogc-2026-v2/submission_build"
for p in (V5, SB):
    if p not in sys.path:
        sys.path.insert(0, p)
import dump_geom3d as D
BASE = "C:/claude-develop/OGC2026"
RESDIR = os.path.join(V5, "_v5_res")

INSTS = [4, 12, 20, 21, 30, 38]


def main():
    out, order = {}, []
    for i in INSTS:
        data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
        for m in ("cur", "v5"):
            f = os.path.join(RESDIR, f"r{i}_{m}.json")
            if not os.path.exists(f):
                continue
            try:
                rec = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            sol = rec.get("sol")
            if not sol:
                continue
            g = D.geom_from_sol(data, sol, label=f"prob_{i} [{m}]")
            key = f"{i}_{m}"
            g["id"] = i; g["mode"] = m
            out[key] = g
            order.append((i, m, key))
    html = _html(out, order)
    path = f"{BASE}/ogc-2026-v2/docs/v5-vs-current-3d-2026-06-23.html"
    open(path, "w", encoding="utf-8").write(html)
    print(f"[html] {path}  ({len(out)} views)")


def _html(out, order):
    data_json = json.dumps(out, ensure_ascii=False)
    opts = []
    for (i, m, key) in order:
        g = out[key]
        objs = f"{g['obj']:,.0f}" if g.get("obj") is not None else "INFEAS"
        opts.append(f'<option value="{key}">prob_{i}  [{m}]  obj={objs} z3={g.get("z3")}</option>')
    opts = "".join(opts)
    return r"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>v5 vs 현재 3D (공간-시간 패킹)</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
 body{margin:0;background:#0d0f13;color:#e8ebf1;font:14px/1.5 Segoe UI,sans-serif}
 .top{padding:12px 18px;border-bottom:1px solid #262b35;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
 select{background:#1a1e26;color:#e8ebf1;border:1px solid #39404d;border-radius:6px;padding:6px 10px;font-size:14px}
 #plot{width:100vw;height:calc(100vh - 120px)}
 .leg{display:flex;gap:14px;font-size:12.5px}
 .sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:4px}
 .info{color:#969eae;font-size:12.5px} b{color:#5ad1c7}
</style></head><body>
<div class="top">
 <div>해 <select id="sel">""" + opts + r"""</select></div>
 <div class="leg">
   <span><span class="sw" style="background:#3ad1c0"></span>선호베이·정시</span>
   <span><span class="sw" style="background:#f0a030"></span>타베이 추방(z3)</span>
   <span><span class="sw" style="background:#ff5555"></span>지각(z1)</span>
 </div>
 <div class="info" id="meta"></div>
 <div class="info">z=시간, 바닥=베이, 베이 x축 나란히. cur↔v5 전환해 비교.</div>
</div>
<div id="plot"></div>
<script>
const DATA = """ + data_json + r""";
function render(key){
  const d = DATA[key]; const traces=[];
  for(const m of d.meshes){
    traces.push({type:'mesh3d', x:m.x, y:m.y, z:m.z, i:m.i, j:m.j, k:m.k,
      color:m.color, opacity:0.78, flatshading:true, name:m.name, hoverinfo:'name',
      lighting:{ambient:0.65,diffuse:0.6,specular:0.1}});
  }
  for(const f of d.floors){
    traces.push({type:'scatter3d', mode:'lines', x:f.x, y:f.y, z:f.z,
      line:{color:'#55607a',width:3}, name:f.name, hoverinfo:'name'});
  }
  const layout={paper_bgcolor:'#0d0f13', font:{color:'#cfd6e2'}, showlegend:false,
    margin:{l:0,r:0,t:0,b:0},
    scene:{xaxis:{title:'x (베이 나란히)',backgroundcolor:'#0d0f13',gridcolor:'#222'},
           yaxis:{title:'y',backgroundcolor:'#0d0f13',gridcolor:'#222'},
           zaxis:{title:'시간',backgroundcolor:'#0d0f13',gridcolor:'#222'},
           aspectmode:'manual', aspectratio:{x:2.2,y:1,z:1.1},
           camera:{eye:{x:1.9,y:-1.9,z:1.4}}}};
  Plotly.react('plot', traces, layout, {responsive:true});
  const objs = d.obj==null?'INFEAS':d.obj.toLocaleString();
  document.getElementById('meta').innerHTML =
    `<b>prob_${d.id} [${d.mode}]</b> · obj=${objs} · z1=${d.z1} · z3=${d.z3} · 블록 ${d.meshes.length}/${d.n}`;
}
const sel=document.getElementById('sel');
sel.addEventListener('change', e=>render(e.target.value));
render(sel.value);
</script></body></html>"""


if __name__ == "__main__":
    main()
