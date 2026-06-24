"""Phase-2 z3-recovery probe: run one instance and print z1/z2/z3/obj/feas.
Env flags (OGC_FLOOR_RASTER, OGC_FAST_FLOOR_POS_K, OGC_PP_RASTER, OGC_CROSSBAY_RELOCATE,
OGC_FRONTB_TRIES, OGC_FB_DEBUG, ...) are read at import, so the CALLER sets them.
FB_DEBUG/STAGE go to stderr.  Usage: python notes/_z3probe.py prob_1 --timelimit 100
"""
import os, sys, json, time
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
import myalgorithm as M
import ogc_analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

tl = 100.0
if "--timelimit" in sys.argv:
    tl = float(sys.argv[sys.argv.index("--timelimit") + 1])
names = [a for a in sys.argv[1:] if not a.startswith("--") and a not in (str(tl), str(int(tl)))]
if not names:
    names = ["prob_1"]

for name in names:
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    t0 = time.monotonic()
    sol = M.algorithm(prob, tl)
    dt = time.monotonic() - t0
    feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
    print(f"PROBE {name} tl={tl}: z1={o1} z2={o2} z3={o3} obj={obj:.0f} "
          f"wall={dt:.1f}s feas={bool(feas)}", flush=True)
