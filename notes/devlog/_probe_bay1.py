"""DECISIVE PROBE (iter 2): is the catastrophic bay serialization-bound or layout-bound?
Give the worst bay's FIXED layout a long monolithic CP-SAT timing solve and see how far
below the floor's tardiness it can get.
  python notes/devlog/_probe_bay1.py prob_31 [tl]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M  # noqa
from myalgorithm import (_results_from_solution, _cpsat_bay_timing_verified,  # noqa
                         _bay_tardiness_lb)
from utils import Bay  # noqa

inst = sys.argv[1] if len(sys.argv) > 1 else "prob_31"
tl = float(sys.argv[2]) if len(sys.argv) > 2 else 115.0
cap_tag = sys.argv[3] if len(sys.argv) > 3 else "diag0"

prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json", encoding="utf-8"))
cap = json.load(open(ROOT / "results" / "capture" / cap_tag / f"{inst}.json",
                     encoding="utf-8"))
sol = cap["solution"]
blocks = prob["blocks"]
bays = [Bay.from_dict(b, i) for i, b in enumerate(prob["bays"])]
_assign, results, _flat = _results_from_solution(prob, sol)


def bay_tard(by_id):
    return sum(max(0, int(a["exit_time"]) - blocks[b]["due_date"])
               for b, a in by_id.items())


# find worst bay
order = sorted(results.items(), key=lambda kv: -bay_tard(kv[1]))
print(f"[{inst}] cap_tag={cap_tag} reported z1={cap['met']['z1']:.0f}")
for j, by in order:
    if by:
        print(f"  bay {j}: n={len(by)} tard={bay_tard(by):.0f} "
              f"intrinsicLB={_bay_tardiness_lb(list(by), blocks):.0f}")
worst, worst_by = order[0]
print(f"--> worst bay {worst}: n={len(worst_by)} floor_tard={bay_tard(worst_by):.0f}")

# isolate worst bay, give it the FULL time limit (len(work)=1)
iso = {j: (dict(results[j]) if j == worst else {}) for j in results}
t0 = time.monotonic()
sol2 = _cpsat_bay_timing_verified(prob, bays, iso, deadline=t0 + tl, lb_skip=False)
dt = time.monotonic() - t0
if sol2 is None:
    print(f"CP-SAT@{tl:.0f}s: no improvement (dt={dt:.1f}s) -> floor timing is best found")
else:
    _a, res2, _f = _results_from_solution(prob, sol2)
    nt = bay_tard(res2[worst])
    print(f"CP-SAT@{tl:.0f}s (dt={dt:.1f}s): bay {worst} tard "
          f"{bay_tard(worst_by):.0f} -> {nt:.0f}  "
          f"(cut {100*(1-nt/max(1,bay_tard(worst_by))):.1f}%)")
    print("VERDICT:", "SERIALIZATION-bound (better order exists)" if nt < 0.5 * bay_tard(worst_by)
          else "LAYOUT-bound (timing can't fix it; rebalance/replace layout)")
