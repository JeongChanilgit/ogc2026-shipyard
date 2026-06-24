# -*- coding: utf-8 -*-
"""Isolated probe: does _multi_order_reschedule_verified actually run, and how
far is current Z1 from the per-block lower bound (insight 2)?  Run under ogc2025."""
import sys, json, time
sys.path.insert(0, "src")
import myalgorithm as M
from myalgorithm import Bay
from utils import check_feasibility

inst = sys.argv[1] if len(sys.argv) > 1 else "prob_14"
tl = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
prob = json.load(open(f"instances/train/{inst}.json", "r", encoding="utf-8"))

sol = M.algorithm(prob, tl)
rep = check_feasibility(prob, sol)
print(f"[{inst}] base feasible={rep['feasible']} obj={rep['objective']} "
      f"Z1={rep.get('obj1')} Z2={rep.get('obj2')} Z3={rep.get('obj3')}")

assign, results, flat = M._results_from_solution(prob, sol)
bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
blocks = prob["blocks"]

tot_cur = tot_lb = 0.0
gap_bays = 0
for j, by in results.items():
    if not by:
        continue
    cur = sum(max(0, by[b]["exit_time"] - blocks[b]["due_date"]) for b in by)
    lb = M._bay_tardiness_lb(list(by), blocks)
    tot_cur += cur
    tot_lb += lb
    if cur - lb > 1e-9:
        gap_bays += 1
        if gap_bays <= 12:
            print(f"  bay {j:3d}: n={len(by):3d} cur_tard={cur:8.0f} LB={lb:8.0f} GAP={cur-lb:8.0f}")
print(f"TOTAL cur_tard={tot_cur:.0f}  per-block LB={tot_lb:.0f}  "
      f"recoverable_gap={tot_cur-tot_lb:.0f}  ({gap_bays} bays have a gap)")

t = time.monotonic()
cand = M._multi_order_reschedule_verified(prob, bays, results,
                                          deadline=t + 30, lb_skip=False)
print("multi_reschedule returned:", "None" if cand is None else "candidate")
if cand is not None:
    rep2 = check_feasibility(prob, cand)
    print(f"  cand feasible={rep2['feasible']} obj={rep2['objective']} "
          f"Z1={rep2.get('obj1')} (base Z1={rep.get('obj1')})")
