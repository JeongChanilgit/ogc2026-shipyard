"""Part 1: find the THRESHOLD initial z1 for prob_20 such that a single 90s
postprocess drives z1 < 10.  Generate feasible initials at a range of z1 (by
short-postprocessing the floor), then run a fresh 90s postprocess on each.
Usage: python notes/_part1_threshold.py prob_20
Env: OGC_PP_ROUND_S=0 (single-pass postprocess).
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
os.environ["OGC_PP_ROUND_S"] = "0"  # single pass for the engine under test
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
    bay_areas = [prob["bays"][j]["width"] * prob["bays"][j]["height"] for j in range(n_bays)]
    avg = sum(bay_areas) / n_bays
    bay_u = [avg / a for a in bay_areas]
    feasible_bays = M._feasible_bays(prob["blocks"], bays)

    def pp(sol, rep, secs):
        out = M._postprocess_verified_solution(
            prob, sol, rep, bays, feasible_bays, bay_u, deadline=time.monotonic() + secs)
        return out[0] if out else sol

    print(f"building pos_k=2 floor for {name}...", flush=True)
    set_pos_k_override(2)
    floor = greedyalgorithm(prob, 80.0, repair_mode="auto")
    set_pos_k_override(0)
    floor_rep = check_feasibility(prob, floor)
    print(f"  floor z1={z1of(prob, floor):.0f}", flush=True)

    # Generate initials at a spread of z1 by short-postprocessing the floor.
    print("generating initials at varied z1...", flush=True)
    initials = [("floor", z1of(prob, floor), floor)]
    for D in [6, 12, 22, 40]:
        s = pp(floor, floor_rep, D)
        initials.append((f"pp{D}s", z1of(prob, s), s))

    print(f"\n=== Part1 threshold {name}: initial_z1 -> final_z1 after single 90s postprocess ===", flush=True)
    rows = sorted(initials, key=lambda r: -r[1])  # (lbl, z1, sol) sorted by z1 desc
    for lbl, z1i, soli in rows:
        repi = check_feasibility(prob, soli)
        t0 = time.monotonic()
        fin = pp(soli, repi, 90.0)
        z1f = z1of(prob, fin)
        dt = time.monotonic() - t0
        mark = "  <-- <10 OK" if z1f < 10 else ("  (<30)" if z1f < 30 else "")
        print(f"  init z1={z1i:6.0f} ({lbl:6s}) -> 90s -> z1={z1f:6.0f}  wall={dt:.0f}s{mark}", flush=True)
