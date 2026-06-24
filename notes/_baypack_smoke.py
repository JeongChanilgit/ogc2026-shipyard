"""Smoke test: can cp-sat/bay_pack_cp.solve_bay() be reused from a script?
De-risks import path (cp-sat is a separate folder), _DATA global, and a real
per-bay solve before wiring into lean legacy stage 2.

Usage: python notes/_baypack_smoke.py prob_14 [time_budget]
Assigns each block to its argmax-preference bay (just to get a realistic per-bay
block set), then solves the LARGEST bay's set with solve_bay.
"""
import os
import sys
import json
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "cp-sat"))


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else "prob_14"
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    path = os.path.join(ROOT, "instances", "train", inst + ".json")
    with open(path, encoding="utf-8") as f:
        prob_info = json.load(f)

    import data
    import bay_pack_cp

    prob = data.parse(prob_info)
    H = data.horizon(prob)
    print(f"[smoke] {inst}: n_blocks={prob.n_blocks} n_bays={prob.n_bays} horizon={H}")

    # crude assignment: each block -> argmax-preference fitting bay
    groups = {j: [] for j in range(prob.n_bays)}
    for bs in prob.blocks:
        fit = bs.fitting_bays or list(range(prob.n_bays))
        j = max(fit, key=lambda jj: bs.prefs[jj] if jj < len(bs.prefs) else 0)
        groups[j].append(bs)

    sizes = {j: len(g) for j, g in groups.items()}
    print(f"[smoke] group sizes: {sizes}")
    jbig = max(groups, key=lambda j: len(groups[j]))
    block_specs = groups[jbig]
    baysp = prob.bays[jbig]
    print(f"[smoke] solving bay {jbig} (W={baysp.W} H={baysp.H}) "
          f"with {len(block_specs)} blocks, budget={budget}s ...")

    t0 = time.monotonic()
    placements, tard, status = bay_pack_cp.solve_bay(
        baysp, block_specs, H, budget, workers=4)
    dt = time.monotonic() - t0
    print(f"[smoke] status={status} total_tardiness={tard} "
          f"n_placed={len(placements) if placements else 0} wall={dt:.2f}s")
    if placements:
        sample = list(placements.items())[:2]
        print(f"[smoke] sample placement: {sample}")
    print("SMOKE_DONE")


if __name__ == "__main__":
    main()
