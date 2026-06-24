"""Direct driver for src/z3race.z3_race_candidate on a captured solution."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M          # noqa: E402
import z3race                    # noqa: E402

inst = sys.argv[1] if len(sys.argv) > 1 else "prob_16"
tag = sys.argv[2] if len(sys.argv) > 2 else "base600_r1"
budget = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0

prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json",
                      encoding="utf-8"))
cap = json.load(open(ROOT / "results" / "capture" / tag / f"{inst}.json",
                     encoding="utf-8"))
sol = cap["solution"]
print("base met:", cap["met"])
res = M._results_from_solution(prob, sol)[1]
bays_obj = [M.Bay(b["width"], b["height"]) for b in prob["bays"]]
fb = M._feasible_bays(prob["blocks"], bays_obj)
bay_areas = [b["width"] * b["height"] for b in prob["bays"]]
avg = sum(bay_areas) / len(bay_areas)
bay_u = [avg / a for a in bay_areas]
t0 = time.monotonic()
out = z3race.z3_race_candidate(prob, bays_obj, fb, res, bay_u,
                               deadline=time.monotonic() + budget)
print(f"took {time.monotonic() - t0:.1f}s -> "
      f"{'None' if out is None else 'candidate'}")
if out is not None:
    chk = M.check_feasibility(prob, out)
    print("feasible:", chk["feasible"], "obj:", chk.get("objective"),
          "z1:", chk.get("obj1"), "z2:", chk.get("obj2"),
          "z3:", chk.get("obj3"))
