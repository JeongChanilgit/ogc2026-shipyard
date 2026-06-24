import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solver_orig
import utils

data = json.load(open(os.path.join("..", "..", "instances", "train", "prob_1.json"), encoding="utf-8"))
for b in (40.0, 80.0):
    try:
        t0 = time.time()
        sol = solver_orig.algorithm(data, b)
        wall = time.time() - t0
        r = utils.check_feasibility(data, sol)
        obj = r.get("objective") if isinstance(r, dict) else None
        print(f"solver_orig prob_1 @budget={b}: obj={obj}  wall={wall:.1f}s", flush=True)
    except Exception as e:
        import traceback
        print(f"solver_orig prob_1 @budget={b}: CRASH {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
