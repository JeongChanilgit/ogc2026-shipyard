"""Single diagnostic solver run with FB-uncap + OGC_FB_DEBUG, to see where
Front B's z3 harvest stops (passes, adoptions, ins_none, rd_try/rd_ok).
Usage: python notes/_fb_debug_run.py prob_18 600
[FB]/[FB2] trace goes to stderr -- redirect it to a file.
"""
import json
import sys
import time

sys.path.insert(0, "src")
sys.path.insert(0, "tools")
from myalgorithm import algorithm          # noqa: E402
import ogc_analysis as A                   # noqa: E402

inst = sys.argv[1] if len(sys.argv) > 1 else "prob_18"
tl = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
prob = json.load(open(f"instances/train/{inst}.json", encoding="utf-8"))
t0 = time.monotonic()
sol = algorithm(prob, tl)
dt = time.monotonic() - t0
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
print(json.dumps({"inst": inst, "wall": round(dt, 2), "feas": bool(feas),
                  "z1": o1, "z2": o2, "z3": o3, "obj": obj}))
