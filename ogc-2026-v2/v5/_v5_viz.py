"""_v5_viz.py -- render v5 (and saved current) solutions with the existing
interactive Three.js viewer (ogc-2026-v2/viz.py write_viz)."""
import sys, os, json, subprocess

V2 = r"C:/claude-develop/OGC2026/ogc-2026-v2"
if V2 not in sys.path:
    sys.path.insert(0, V2)
from viz import trace_from_solution, write_viz

BASE = "C:/claude-develop/OGC2026"
V5RES = os.path.join(V2, "v5", "_v5_res")
OUT = os.path.join(V2, "out")
os.makedirs(OUT, exist_ok=True)
INSTS = [int(a) for a in sys.argv[1:]] or [4, 12, 20, 21, 30, 38]

written = {}
for i in INSTS:
    data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
    for m in ("v5", "cur"):
        f = os.path.join(V5RES, f"r{i}_{m}.json")
        if not os.path.exists(f):
            continue
        rec = json.load(open(f, encoding="utf-8"))
        sol = rec.get("sol")
        if not sol:
            continue
        trace = trace_from_solution(data, sol, instance_name=f"prob_{i} [{m}] obj={rec.get('obj')}")
        out = os.path.join(OUT, f"viz_{m}_prob_{i}.html")
        write_viz(trace, out)
        written[(i, m)] = out
        print(f"wrote {out}  (obj={rec.get('obj')} z1={rec.get('z1')} z3={rec.get('z3')})", flush=True)

# open a curated contrast set: v5 win (prob_4), v5 z1-explosion (prob_20) + its cur
for key in [(4, "v5"), (20, "v5"), (20, "cur"), (12, "v5")]:
    if key in written and os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", written[key]], shell=False)
