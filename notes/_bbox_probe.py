"""Probe: can bbox_pack pack prob_20's big bays to low tardiness given GENEROUS
per-bay budget?  Runs the floor, then _bbox_pack_bay per bay at budget=BUDGET each,
reporting per-bay (n_blocks, tard_before, tard_after, wall).  Determines whether the
bbox-primary redesign is viable (bbox solvable per bay) or needs decomposition.

Usage: python notes/_bbox_probe.py prob_20 --budget 30
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
import myalgorithm as M
from baseline_greedy import greedyalgorithm
from utils import Bay

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

def bay_tard(res, blocks):
    return sum(max(0, res[b]["exit_time"] - blocks[b]["due_date"]) for b in res)

if __name__ == "__main__":
    name = sys.argv[1]
    budget = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 30.0
    nslabs = int(sys.argv[sys.argv.index("--slabs") + 1]) if "--slabs" in sys.argv else 1
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    blocks = prob["blocks"]
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]

    # Floor layout
    print(f"running greedy floor for {name}...", flush=True)
    t0 = time.monotonic()
    sol = greedyalgorithm(prob, 60.0, repair_mode="simple")
    print(f"  floor wall={time.monotonic()-t0:.1f}s", flush=True)
    _assign, results, _flat = M._results_from_solution(prob, sol)

    print(f"\n=== bbox_pack per-bay probe: {name} budget={budget}s/bay slabs={nslabs} ===", flush=True)
    tot_before = tot_after = 0.0
    for j in sorted(results):
        ids = list(results[j])
        if not ids:
            continue
        tb = bay_tard(results[j], blocks)
        lb = M._bay_tardiness_lb(ids, blocks)
        t0 = time.monotonic()
        res = M._bbox_pack_bay(prob, bays[j], j, ids, budget, warm=results[j], n_slabs=nslabs)
        dt = time.monotonic() - t0
        ta = bay_tard(res, blocks) if res else float("inf")
        tot_before += tb
        tot_after += min(tb, ta) if res else tb
        flag = "OK" if (res and ta <= tb) else ("FAIL" if not res else "WORSE")
        print(f"  bay{j}: n={len(ids):3d}  tard {tb:7.0f} -> {ta:7.0f}  (lb={lb:.0f})  wall={dt:5.1f}s  [{flag}]", flush=True)
    print(f"  >> TOTAL tard {tot_before:.0f} -> {tot_after:.0f}", flush=True)
