"""_gen_real.py -- generate a REAL submission-pipeline solution and save it
for v3 post-processing experiments. Calls the actual submission entry
myalgorithm.algorithm(prob_info, timelimit).

Usage: python _gen_real.py [prob=prob_29] [timelimit=120]
"""
import sys
import os
import json
import time

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

import myalgorithm  # noqa: E402

BASE = "C:/claude-develop/OGC2026"


def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_29"
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    data = json.load(open(f"{BASE}/instances/train/{prob}.json", encoding="utf-8"))
    t0 = time.time()
    sol = myalgorithm.algorithm(data, tl)
    wall = time.time() - t0
    out = f"{BASE}/ogc-2026-v3/real_{prob}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sol, f)
    print(f"gen {prob} done  wall={wall:.1f}s  -> {out}", flush=True)


if __name__ == "__main__":
    main()
