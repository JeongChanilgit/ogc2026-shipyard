"""Soundness verify for OGC_PP_RASTER: run with VERIFY on so every raster-disjoint
SKIP also runs the 5 Shapely calls; _PP_RASTER_STAT['violations'] must be 0 (raster
never claims disjoint when Shapely sees a conflict).  Also prints z1/obj/feas to
confirm the run is healthy.  Env flags are read at import, so set them first.
Usage: python notes/_pp_raster_verify.py prob_20 prob_14 --timelimit 100
"""
import os, sys, json, time
os.environ["OGC_FLOOR_RASTER"] = "1"
os.environ["OGC_PP_RASTER"] = "1"
os.environ["OGC_PP_RASTER_VERIFY"] = "1"

sys.path.insert(0, "src"); sys.path.insert(0, "tools")
import myalgorithm as M
import ogc_analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

tl = 100.0
if "--timelimit" in sys.argv:
    tl = float(sys.argv[sys.argv.index("--timelimit") + 1])
names = [a for a in sys.argv[1:] if not a.startswith("--")
         and a != str(tl) and a != str(int(tl))]
if not names:
    names = ["prob_20"]

for name in names:
    M._PP_RASTER_STAT["skips"] = 0
    M._PP_RASTER_STAT["violations"] = 0
    M._PP_RASTER_STAT["examples"] = []
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    t0 = time.monotonic()
    sol = M.algorithm(prob, tl)
    dt = time.monotonic() - t0
    feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
    st = M._PP_RASTER_STAT
    print(f"\n==== PP_RASTER VERIFY {name} tl={tl} ====", flush=True)
    print(f"z1={o1} z2={o2} z3={o3} obj={obj:.0f} wall={dt:.1f}s feas={bool(feas)}",
          flush=True)
    print(f"raster skips={st['skips']}  VIOLATIONS={st['violations']}  "
          f"examples={st['examples']}", flush=True)
    print("  -> SOUND" if st["violations"] == 0 and feas
          else "  -> *** UNSOUND / INFEASIBLE ***", flush=True)
