"""Test the user's hypothesis: a FAST STRUCTURE floor (positions + serialised
times, OGC_FLOOR_SERIAL, skips crane search) + 90s postprocess -> low z1?
Reports: serial floor wall + z1, then z1 after a single 90s postprocess.
Compares against the normal pos_k=2 floor's z1 as reference.
Usage: python notes/_serialfloor_test.py prob_20
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
os.environ["OGC_PP_ROUND_S"] = "0"
import myalgorithm as M
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

    print(f"=== SERIAL (fast structure) floor test: {name} ===", flush=True)
    os.environ["OGC_FLOOR_SERIAL"] = "1"
    set_pos_k_override(2)
    t0 = time.monotonic()
    floor = greedyalgorithm(prob, 200.0, repair_mode="auto")
    dt = time.monotonic() - t0
    set_pos_k_override(0)
    os.environ["OGC_FLOOR_SERIAL"] = "0"
    feas = check_feasibility(prob, floor)
    print(f"serial floor: wall={dt:.1f}s  z1={z1of(prob, floor):.0f}  feasible={bool(feas.get('feasible'))}", flush=True)

    if feas.get("feasible"):
        t0 = time.monotonic()
        fin = pp(floor, feas, 90.0)
        print(f"  -> 90s postprocess -> z1={z1of(prob, fin):.0f}  wall={time.monotonic()-t0:.0f}s", flush=True)
    else:
        print("  serial floor INFEASIBLE -> cannot postprocess (gate needs feasible base)", flush=True)
