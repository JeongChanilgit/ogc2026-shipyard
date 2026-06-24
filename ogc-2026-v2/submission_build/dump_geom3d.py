"""dump_geom3d.py -- run the v2 solver on a few instances, then emit ONE
self-contained 3D HTML (plotly) showing each instance's full bay layout as
space-time prisms: footprint polygon extruded over [entry, exit].

z = time, floor = bay footprint, bays placed side-by-side along x.
color: teal = preferred bay & on-time | orange = displaced (wrong bay) | red = tardy.

usage: dump_geom3d.py 4 12 20      (instance ids; default 4 12 20)
env: OGC_PLACE_W1_SCALE / OGC_TOSS / OGC_FIXOPT / OGC_PP_MOVEALL / OGC_V2_CAP / TL via DGTL
"""
import os, sys, json, time

os.environ.setdefault("OGC_NO_V1", "1")
os.environ.setdefault("OGC_PLACE_W1_SCALE", "0.5")
os.environ.setdefault("OGC_TOSS", "1")
os.environ.setdefault("OGC_FIXOPT", "1")
os.environ.setdefault("OGC_PP_MOVEALL", "1")
os.environ.setdefault("OGC_V2_CAP", "110")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
BASE = "C:/claude-develop/OGC2026"
TL = float(os.environ.get("DGTL", "120"))

import utils
from shapely.geometry import Polygon as SPoly, Point as SPoint
from shapely.ops import triangulate as shp_triangulate


def tri_polygon(verts):
    """Return list of triangles (each 3 indices into verts) covering polygon interior."""
    n = len(verts)
    if n < 3:
        return []
    poly = SPoly(verts)
    if not poly.is_valid or poly.area <= 0:
        # fan fallback
        return [(0, k, k + 1) for k in range(1, n - 1)]
    idx = {tuple(round(c, 6) for c in v): i for i, v in enumerate(verts)}
    tris = []
    for tg in shp_triangulate(poly):
        c = tg.centroid
        if not poly.contains(c):
            continue
        tcoords = list(tg.exterior.coords)[:3]
        try:
            ti = tuple(idx[tuple(round(x, 6) for x in pt)] for pt in tcoords)
            tris.append(ti)
        except KeyError:
            # vertex introduced by triangulation; append it
            pass
    if not tris:   # fallback
        return [(0, k, k + 1) for k in range(1, n - 1)]
    return tris


def prism_mesh(verts2d, z0, z1, xoff):
    """Build a Mesh3d (x,y,z,i,j,k) for polygon verts2d extruded z0->z1, x shifted by xoff."""
    n = len(verts2d)
    xs, ys, zs = [], [], []
    # bottom ring (0..n-1), top ring (n..2n-1)
    for (vx, vy) in verts2d:
        xs.append(vx + xoff); ys.append(vy); zs.append(z0)
    for (vx, vy) in verts2d:
        xs.append(vx + xoff); ys.append(vy); zs.append(z1)
    I, J, K = [], [], []
    tris = tri_polygon(verts2d)
    for (a, b, c) in tris:          # bottom cap
        I.append(a); J.append(b); K.append(c)
    for (a, b, c) in tris:          # top cap
        I.append(a + n); J.append(b + n); K.append(c + n)
    for e in range(n):             # side walls
        a, b = e, (e + 1) % n
        I.append(a); J.append(b); K.append(b + n)
        I.append(a); J.append(b + n); K.append(a + n)
    return xs, ys, zs, I, J, K


def geom_from_sol(data, sol, label=""):
    """Build the 3D viz dict (meshes/floors + obj) from a finished solution dict."""
    r = utils.check_feasibility(data, sol)
    blocks = data["blocks"]
    bays = data["bays"]

    def bay_dim(b):
        return (b.get("width") or b.get("W") or b.get("size", [0, 0])[0],
                b.get("height") or b.get("H") or b.get("size", [0, 0])[1])

    # parse operations -> per-block entry/exit/placement
    recs = {}
    for tstr, ops in sol.get("operations", {}).items():
        t = int(tstr)
        for op in ops:
            bid = op["block_id"]
            if op.get("type") == "ENTRY":
                recs.setdefault(bid, {})[ "entry"] = t
                recs[bid]["bay"] = op["bay_id"]
                recs[bid]["x"] = op["x"]; recs[bid]["y"] = op["y"]
                recs[bid]["orient"] = op["orient_idx"]
            elif op.get("type") == "EXIT":
                recs.setdefault(bid, {})["exit"] = t

    # bay x-offsets (side by side)
    dims = [bay_dim(b) for b in bays]
    xoff = []
    acc = 0.0
    gap = max((w for w, h in dims), default=10) * 0.25 + 5
    for (w, h) in dims:
        xoff.append(acc); acc += w + gap

    meshes = []
    for bid, rc in recs.items():
        if "entry" not in rc or "exit" not in rc:
            continue
        j = rc["bay"]
        blk = utils.Block.from_instance(bid, data, x=rc["x"], y=rc["y"], orient_idx=rc["orient"])
        layers = blk.layers_at_pos()
        if not layers or not layers[0]:
            continue
        verts = [(float(v[0]), float(v[1])) for v in layers[0]]
        due = blocks[bid].get("due_date", 0)
        prefs = blocks[bid]["bay_preferences"]
        pref = max(range(len(prefs)), key=lambda k: prefs[k])
        tardy = rc["exit"] > due
        if tardy:
            color = "#ff5555"; status = "tardy"
        elif j != pref:
            color = "#f0a030"; status = "displaced(wrong bay)"
        else:
            color = "#3ad1c0"; status = "preferred/on-time"
        xs, ys, zs, I, J, K = prism_mesh(verts, rc["entry"], rc["exit"], xoff[j])
        meshes.append({
            "x": [round(v, 2) for v in xs], "y": [round(v, 2) for v in ys],
            "z": [round(v, 2) for v in zs], "i": I, "j": J, "k": K,
            "color": color,
            "name": f"blk{bid} bay{j} t[{rc['entry']},{rc['exit']}] due{due} {status}",
        })

    # bay floor rectangles (wireframe) at z=0
    floors = []
    for j, (w, h) in enumerate(dims):
        ox = xoff[j]
        floors.append({"x": [ox, ox + w, ox + w, ox, ox], "y": [0, 0, h, h, 0],
                       "z": [0, 0, 0, 0, 0], "name": f"bay{j} {int(w)}x{int(h)}"})

    return {
        "label": label, "obj": r.get("objective"), "z1": r.get("obj1"),
        "z2": r.get("obj2"), "z3": r.get("obj3"),
        "n": len(blocks), "nbay": len(bays),
        "meshes": meshes, "floors": floors,
    }


def run_instance(i):
    import myalgorithm_fix as M
    data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
    sol = M.algorithm(data, TL)
    d = geom_from_sol(data, sol)
    d["id"] = i
    return d


def main():
    ids = [int(a) for a in sys.argv[1:]] or [4, 12, 20]
    out = {}
    for i in ids:
        t0 = time.time()
        print(f"[run] prob_{i} ...", flush=True)
        out[str(i)] = run_instance(i)
        print(f"[done] prob_{i} obj={out[str(i)]['obj']:,.0f} "
              f"z1={out[str(i)]['z1']} z3={out[str(i)]['z3']} "
              f"meshes={len(out[str(i)]['meshes'])} ({time.time()-t0:.0f}s)", flush=True)
    html = _build_html(out, ids)
    path = f"{BASE}/ogc-2026-v2/docs/instances-3d-2026-06-23.html"
    open(path, "w", encoding="utf-8").write(html)
    print(f"[html] {path}", flush=True)


def _build_html(out, ids):
    data_json = json.dumps(out, ensure_ascii=False)
    opts = "".join(f'<option value="{i}">prob_{i}  (N={out[str(i)]["n"]}, '
                   f'{out[str(i)]["nbay"]}bay, obj={out[str(i)]["obj"]:,.0f})</option>'
                   for i in ids)
    return r"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>OGC2026 인스턴스 3D (공간-시간 패킹)</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
 body{margin:0;background:#0d0f13;color:#e8ebf1;font:14px/1.5 Segoe UI,sans-serif}
 .top{padding:12px 18px;border-bottom:1px solid #262b35;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
 select{background:#1a1e26;color:#e8ebf1;border:1px solid #39404d;border-radius:6px;padding:6px 10px;font-size:14px}
 #plot{width:100vw;height:calc(100vh - 120px)}
 .leg{display:flex;gap:14px;font-size:12.5px}
 .sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:4px}
 .info{color:#969eae;font-size:12.5px}
 b{color:#5ad1c7}
</style></head><body>
<div class="top">
 <div>인스턴스 <select id="sel">""" + opts + r"""</select></div>
 <div class="leg">
   <span><span class="sw" style="background:#3ad1c0"></span>선호베이·정시</span>
   <span><span class="sw" style="background:#f0a030"></span>타베이 추방(z3)</span>
   <span><span class="sw" style="background:#ff5555"></span>지각(z1)</span>
 </div>
 <div class="info" id="meta"></div>
 <div class="info">축: <b>z=시간</b>, 바닥=베이 footprint, 베이들 x축 나란히. 회전·줌·블록 호버.</div>
</div>
<div id="plot"></div>
<script>
const DATA = """ + data_json + r""";
function render(id){
  const d = DATA[id]; const traces=[];
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
           zaxis:{title:'시간 (entry→exit)',backgroundcolor:'#0d0f13',gridcolor:'#222'},
           aspectmode:'manual', aspectratio:{x:2.2,y:1,z:1.1},
           camera:{eye:{x:1.9,y:-1.9,z:1.4}}}};
  Plotly.react('plot', traces, layout, {responsive:true});
  document.getElementById('meta').innerHTML =
    `<b>prob_${d.id}</b> · obj=${d.obj.toLocaleString()} · z1=${d.z1} · z3=${d.z3} · 블록 ${d.meshes.length}/${d.n}`;
}
document.getElementById('sel').addEventListener('change', e=>render(e.target.value));
render('""" + str(ids[0]) + r"""');
</script></body></html>"""


if __name__ == "__main__":
    main()
