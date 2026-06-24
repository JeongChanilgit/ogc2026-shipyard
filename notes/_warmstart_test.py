"""Test the user's hypothesis: if the postprocess is given a GOOD initial solution
(z1~64), does it drive z1 much lower (toward 0) with fresh time, or is it stuck at
the assignment bbox-floor?
Usage: python notes/_warmstart_test.py prob_20 pk2adaptive 100
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
import myalgorithm as M
from utils import Bay, check_feasibility
import ogc_analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

if __name__ == "__main__":
    name = sys.argv[1]
    tag = sys.argv[2]
    extra = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    cap = json.load(open(os.path.join(ROOT, "results", "capture", tag, name + ".json")))
    sol = cap["solution"]
    feas0, obj0, z10, z20, z30 = A.obj_tuple(prob, sol)
    print(f"START: z1={z10} obj={obj0:.0f} feas={bool(feas0)}", flush=True)

    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    blocks_data = prob["blocks"]
    n_bays = len(bays)
    bay_areas = [prob["bays"][j]["width"] * prob["bays"][j]["height"] for j in range(n_bays)]
    avg = sum(bay_areas) / n_bays
    bay_u = [avg / a for a in bay_areas]
    feasible_bays = M._feasible_bays(blocks_data, bays)
    rep = check_feasibility(prob, sol)

    # Run postprocess repeatedly (iterative warm-start), each round fresh `extra` sec.
    cur_sol = sol
    cur_rep = rep
    for rnd in range(1, 6):
        t0 = time.monotonic()
        out = M._postprocess_verified_solution(
            prob, cur_sol, cur_rep, bays, feasible_bays, bay_u,
            deadline=time.monotonic() + extra)
        dt = time.monotonic() - t0
        if out is None:
            print(f"round{rnd}: postprocess returned None (no improvement), wall={dt:.1f}s", flush=True)
            break
        new_sol, new_obj = out
        feas, obj, z1, z2, z3 = A.obj_tuple(prob, new_sol)
        print(f"round{rnd}: z1={z1} obj={obj:.0f} feas={bool(feas)} wall={dt:.1f}s", flush=True)
        if z1 >= (A.obj_tuple(prob, cur_sol)[2] - 1e-9):
            print(f"  -> no further z1 improvement (stuck at ~{z1}); stop", flush=True)
            cur_sol = new_sol
            break
        cur_sol = new_sol
        cur_rep = check_feasibility(prob, new_sol)
