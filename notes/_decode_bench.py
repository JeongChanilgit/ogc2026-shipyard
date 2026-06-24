# -*- coding: utf-8 -*-
"""Isolated decode-speed microbench: time a clean re-decode of EVERY bay of an
instance (fixed assignment) under whatever OGC_* flags the parent set.
Prints: config wall (sum over bays) + total tardiness (Z1 proxy).
Module-level flags are read at import, so the PARENT sets env per invocation.

Usage:  conda run -n ogc2025 python notes/_decode_bench.py [inst] [sol.json]
"""
import os, sys, json, time
sys.path.insert(0, "src")
from utils import Bay
import myalgorithm as M

inst = sys.argv[1] if len(sys.argv) > 1 else "prob_6"
solp = sys.argv[2] if len(sys.argv) > 2 else "results/z1_exp_B/sol_prob_6__base.json"
prob = json.load(open(f"instances/train/{inst}.json", encoding="utf-8"))
sol = json.load(open(solp, encoding="utf-8"))
blocks = prob["blocks"]
bays = [Bay.from_dict(d, j) for j, d in enumerate(prob["bays"])]

# bay -> [block ids] from the saved solution
by_bay = {}
for t_str, ops in sol["operations"].items():
    for op in ops:
        if op["type"] == "ENTRY":
            by_bay.setdefault(op["bay_id"], []).append(op["block_id"])

cfg = (f"EARLY={os.environ.get('OGC_DECODE_EARLY_EXIT','0')} "
       f"EPS={os.environ.get('OGC_DECODE_EARLY_EPS','0')} "
       f"FAST_CRANE={os.environ.get('OGC_FAST_CRANE','0')} "
       f"CAND_CAP={os.environ.get('OGC_CAND_CAP','0')}/{os.environ.get('OGC_CAND_CAP_MIN','0')}")

# warm caches once (poly cache) so timing reflects steady state on bay 0 only excluded
maxbays = int(sys.argv[3]) if len(sys.argv) > 3 else 999
total_wall = 0.0
total_tard = 0.0
per = []
for j in sorted(by_bay)[:maxbays]:
    ids = by_bay[j]
    order = list(M._orderings(list(ids), blocks, True)[0])
    t0 = time.monotonic()
    # cand_cap=0 -> module-level _CAND_CAP / _CAND_CAP_MIN (set via env) apply.
    res, forced = M._decode_bay(bays[j], j, order, blocks, deadline=None, cand_cap=0)
    w = time.monotonic() - t0
    tard = M._bay_tardiness(res, blocks) if res else float("inf")
    total_wall += w
    total_tard += tard
    per.append((j, len(ids), round(w, 2), int(tard), len(forced or ())))

print(f"[{inst}] {cfg}")
print(f"  TOTAL decode wall={total_wall:.2f}s  total_tard={total_tard:.0f}")
for j, n, w, tard, f in per:
    print(f"    bay {j}: n={n:3d} wall={w:6.2f}s tard={tard:6d} forced={f}")
