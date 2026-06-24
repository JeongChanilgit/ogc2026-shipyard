"""_allcheck.py -- run myalgorithm @TL=120 on ALL 40 train instances, check
feasibility, accumulate results so progress can be inspected mid-run.
Usage:  python _allcheck.py
"""
import json
import time
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

import myalgorithm  # noqa: E402
import utils        # noqa: E402

BASE = "C:/claude-develop/OGC2026"
OUT = f"{BASE}/submissions/v3pp_allcheck.txt"


def main():
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("=== v3postproc submission ALL40 @TL=120 feasibility/obj ===\n")
        f.flush()
        for i in range(1, 41):
            data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
            t0 = time.time()
            try:
                sol = myalgorithm.algorithm(data, 120.0)
                wall = time.time() - t0
                r = utils.check_feasibility(data, sol)
                obj = r.get("objective")
                stage = r.get("stage")
                feas = obj is not None
            except Exception as e:
                wall = time.time() - t0
                obj, stage, feas = None, f"CRASH:{type(e).__name__}", False
            tag = "set1" if i <= 20 else "set2"
            line = f"{tag} prob_{i:<3} obj={obj} stage={stage} feas={feas} wall={wall:.0f}s"
            print(line, flush=True)
            f.write(line + "\n")
            f.flush()
        f.write("=== DONE ===\n")


if __name__ == "__main__":
    main()
