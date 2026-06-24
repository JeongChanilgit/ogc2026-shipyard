"""Verify OGC_FLOOR_GRID byte-identical floor + measure speedup.

For prob_6 / prob_14 / prob_20: run greedyalgorithm with the grid OFF then ON,
compare z1 (must be IDENTICAL) and wall time.  Also compares full placements when
z1 matches, as an extra byte-identity signal.
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import baseline_greedy
from baseline_greedy import greedyalgorithm, set_pos_k_override
import ogc_analysis


def load(prob):
    with open(os.path.join(ROOT, "instances", "train", f"{prob}.json")) as f:
        return json.load(f)


def placements(sol):
    """Stable signature of ENTRY placements for byte-identity comparison."""
    out = []
    for t, ops in sol.get("operations", {}).items():
        for op in ops:
            if op.get("type") == "ENTRY":
                out.append((op["block_id"], op["bay_id"], op["x"], op["y"],
                            op["orient_idx"], int(t)))
    out.sort()
    return out


def run(prob, grid_on):
    if grid_on:
        os.environ["OGC_FLOOR_GRID"] = "1"
    else:
        os.environ.pop("OGC_FLOOR_GRID", None)
    set_pos_k_override(2)
    pinfo = load(prob)
    t0 = time.time()
    sol = greedyalgorithm(pinfo, 200.0, repair_mode="auto")
    dt = time.time() - t0
    z1 = ogc_analysis.obj_tuple(pinfo, sol)[2]
    return sol, z1, dt


def main():
    rows = []
    for prob in ["prob_6", "prob_14", "prob_20"]:
        sol_off, z1_off, t_off = run(prob, False)
        sol_on, z1_on, t_on = run(prob, True)
        same_z1 = (z1_off == z1_on)
        same_pl = (placements(sol_off) == placements(sol_on))
        speedup = (t_off / t_on) if t_on > 0 else float("nan")
        rows.append((prob, z1_off, z1_on, same_z1, same_pl, t_off, t_on, speedup))

    print("\n=== OGC_FLOOR_GRID verification (pos_k=2, tl=200, repair=auto) ===")
    hdr = f"{'prob':<8} {'z1_off':>10} {'z1_on':>10} {'z1==?':>6} {'place==?':>8} {'t_off':>8} {'t_on':>8} {'speedup':>8}"
    print(hdr)
    print("-" * len(hdr))
    all_ok = True
    for prob, z1_off, z1_on, same_z1, same_pl, t_off, t_on, su in rows:
        all_ok = all_ok and same_z1
        print(f"{prob:<8} {z1_off:>10} {z1_on:>10} "
              f"{'YES' if same_z1 else 'NO':>6} {'YES' if same_pl else 'NO':>8} "
              f"{t_off:>8.2f} {t_on:>8.2f} {su:>7.2f}x")
    print("-" * len(hdr))
    print("RESULT:", "PASS (all z1 identical)" if all_ok else "FAIL (z1 mismatch)")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
