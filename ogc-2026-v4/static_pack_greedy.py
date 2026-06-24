"""
static_pack_greedy.py -- CORRECT-SCALE greedy static packing test (capstone).

Settles the reachability question cleanly: can the peak contention set S of a
z1-worst bay be co-located simultaneously?  Two prior tests were inconclusive:
  - peak_pack_test (CP-SAT): coarse candidates + 90s timeout -> weak N=33 (lower bound)
  - static_pack_fine (agent): SCALE BUG (computed S area 147.8% = 4x real -> bogus "wall")

This test:
  * reuses peak_pack_test's PROVEN helpers (find_worst_bay, find_peak_coexistence,
    load_instance_and_solution) and the SAME candidate-bound formula crane_cpsat uses,
  * packs S greedily at FINE integer resolution (bottom-left first-fit, all orients),
  * has an AREA SANITY GUARD: prints real S-area% (must be ~30-40%; if ~150% => scale bug).

F = #blocks a correct-scale greedy packer co-locates.
  F >> M (our solution's co-location)  -> packing lever REACHABLE (we serialize needlessly)
  F ~ M                                -> shape wall (z1 structural -> pivot z3)

run: C:/Users/peter/anaconda3/envs/ogc2025/python.exe static_pack_greedy.py
"""
from __future__ import annotations
import os, sys, math, json, time

V4 = os.path.dirname(os.path.abspath(__file__))
if V4 not in sys.path:
    sys.path.insert(0, V4)

import peak_pack_test as ppt          # proven: find_worst_bay/find_peak_coexistence/load
from gridmap import build_shape
from utils import Bay, Block, check_collisions


def _bbox(sh, x, y):
    return (x + sh.min_x, y + sh.min_y, x + sh.max_x, y + sh.max_y)


def _bbox_overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def greedy_pack(data, bay_id, block_ids, step=2):
    """Bottom-left first-fit greedy packing of block_ids into bay (fine resolution).
    Returns (F, area_pct) where F = #co-located, area_pct = real S-area / bay-area."""
    bay_data = data["bays"][bay_id]
    W = int(bay_data["width"]); H = int(bay_data["height"])
    bay = Bay.from_dict(bay_data, bay_id)
    bd_all = data["blocks"]

    # area sanity (scale=2 => footprint_area is 4x real => /4)  -- GUARD
    s_area = sum(build_shape(b, bd_all[b], 0, scale=2).footprint_area / 4.0
                 for b in block_ids)
    bay_area = W * H
    area_pct = 100.0 * s_area / bay_area if bay_area else 0.0

    # big blocks first
    order = sorted(block_ids,
                   key=lambda b: build_shape(b, bd_all[b], 0, scale=2).footprint_area,
                   reverse=True)

    placed = []   # list of (Block, bbox)
    F = 0
    for bid in order:
        bd = bd_all[bid]
        n_or = len(bd["shape"])
        done = False
        for o in range(n_or):
            sh = build_shape(bid, bd, o, scale=2)
            x_lb = max(0, int(math.ceil(-sh.min_x - 1e-9)))
            x_ub = max(x_lb, int(math.floor(W - sh.max_x + 1e-9)))
            y_lb = max(0, int(math.ceil(-sh.min_y - 1e-9)))
            y_ub = max(y_lb, int(math.floor(H - sh.max_y + 1e-9)))
            for yv in range(y_lb, y_ub + 1, step):
                for xv in range(x_lb, x_ub + 1, step):
                    cb = _bbox(sh, xv, yv)
                    conflicters = [pb for (pb, pbb) in placed if _bbox_overlap(cb, pbb)]
                    cand = Block(block_id=bid, block_data=bd, x=xv, y=yv, orient_idx=o)
                    if conflicters and check_collisions(bay, [cand] + conflicters):
                        continue
                    placed.append((cand, cb)); F += 1; done = True; break
                if done:
                    break
            if done:
                break
    return F, area_pct


def run(prob_num, step=2):
    data, sol = ppt.load_instance_and_solution(prob_num)
    worst_bay, bay_z1 = ppt.find_worst_bay(data, sol)
    t_star, S_ideal, S_actual, M = ppt.find_peak_coexistence(data, sol, worst_bay)
    t0 = time.monotonic()
    F, area_pct = greedy_pack(data, worst_bay, S_ideal, step=step)
    wall = time.monotonic() - t0
    return {
        "prob": prob_num, "worst_bay": worst_bay, "bay_z1": bay_z1,
        "S": len(S_ideal), "area_pct": round(area_pct, 1),
        "M_ours": M, "F_greedy": F, "gap_F_M": F - M,
        "wall_s": round(wall, 1),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--probs", nargs="+", type=int, default=[38, 40, 27])
    ap.add_argument("--step", type=int, default=2)
    args = ap.parse_args()

    print(f"[static_pack_greedy] probs={args.probs} step={args.step}", flush=True)
    rows = []
    for p in args.probs:
        print(f"\n=== prob_{p} ===", flush=True)
        try:
            r = run(p, step=args.step)
        except Exception as e:
            import traceback
            print("\n".join(traceback.format_exc().splitlines()[-5:]), flush=True)
            r = {"prob": p, "error": str(e)}
        rows.append(r)
        print(r, flush=True)

    print("\n" + "=" * 92, flush=True)
    print(f"{'prob':>5} {'bay':>4} {'bay_z1':>8} {'|S|':>5} {'area%':>6} "
          f"{'M_ours':>7} {'F_greedy':>9} {'gap':>5} {'wall':>6}", flush=True)
    print("-" * 92, flush=True)
    for r in rows:
        if "error" in r:
            print(f"{r['prob']:>5}  ERROR {r['error']}", flush=True); continue
        print(f"{r['prob']:>5} {r['worst_bay']:>4} {r['bay_z1']:>8.0f} {r['S']:>5} "
              f"{r['area_pct']:>5.1f}% {r['M_ours']:>7} {r['F_greedy']:>9} "
              f"{r['gap_F_M']:>+5} {r['wall_s']:>5.0f}s", flush=True)
    print("=" * 92, flush=True)
    print("\n[GUARD] area% must be ~30-40% (clean). ~150% => scale bug (discard).", flush=True)
    print("[VERDICT] F>>M => packing lever REACHABLE.  F~M => shape wall.", flush=True)

    with open(os.path.join(V4, "static_pack_greedy_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\nsaved: static_pack_greedy_results.json", flush=True)
