"""Test the ANTI-STACKING fast floor (OGC_FLOOR_ANTISTACK): bbox-disjoint-when-
co-present placement (no Shapely crane search) -> fast floor + spread structure.
Reports floor wall+z1+feasibility, then z1 after a single 90s postprocess.
Usage: python notes/_antistack_test.py prob_20
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
os.environ["OGC_PP_ROUND_S"] = "0"
os.environ["OGC_BR_CACHE"] = "1"
import myalgorithm as M
# install the bounding_rect cache the real algorithm() uses (fair floor timing)
try:
    M._install_bounding_rect_cache()
except Exception as e:
    print("BR cache install failed:", e)
from baseline_greedy import greedyalgorithm, set_pos_k_override
from utils import Bay, check_feasibility
import ogc_analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

def z1of(prob, sol):
    return A.obj_tuple(prob, sol)[2]

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "prob_20"
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    n_bays = len(prob["bays"])
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    ba = [prob["bays"][j]["width"] * prob["bays"][j]["height"] for j in range(n_bays)]
    avg = sum(ba) / n_bays
    bay_u = [avg / a for a in ba]
    feasible_bays = M._feasible_bays(prob["blocks"], bays)

    def pp(sol, rep, secs):
        out = M._postprocess_verified_solution(
            prob, sol, rep, bays, feasible_bays, bay_u, deadline=time.monotonic() + secs)
        return out[0] if out else sol

    print(f"=== ANTI-STACKING floor test: {name} ===", flush=True)
    os.environ["OGC_FLOOR_ANTISTACK"] = "1"
    set_pos_k_override(2)
    t0 = time.monotonic()
    floor = greedyalgorithm(prob, 200.0, repair_mode="auto")
    dt = time.monotonic() - t0
    set_pos_k_override(0)
    os.environ["OGC_FLOOR_ANTISTACK"] = "0"
    feas = check_feasibility(prob, floor)
    print(f"anti-stack floor: wall={dt:.1f}s  z1={z1of(prob, floor):.0f}  feasible={bool(feas.get('feasible'))}", flush=True)

    if feas.get("feasible"):
        for rnd in (90.0,):
            t0 = time.monotonic()
            fin = pp(floor, feas, rnd)
            print(f"  -> {rnd:.0f}s postprocess -> z1={z1of(prob, fin):.0f}  wall={time.monotonic()-t0:.0f}s", flush=True)
    else:
        print(f"  INFEASIBLE: {feas.get('reason','?')}", flush=True)
