#!/usr/bin/env python3
"""
crane_headroom.py -- READ-ONLY analysis (imports utils/baseline; edits nothing).

Goal
----
For every tardy block (exit_b > due_b) in a base solution, decisively measure
whether it could have entered the bay EARLIER in a crane-feasible way (= the
decode left tardiness/Z1 headroom on the table) or whether it was crane-forced
to wait because no (x,y,orient) was crane-feasible at any earlier time.

Method (per tardy block b in bay j, release r_b, entry entry_b, exit exit_b)
---------------------------------------------------------------------------
Scan candidate entry times t from r_b up to entry_b (capped at ~40 steps). At
each t, reconstruct the set of blocks PRESENT in bay j (entry<=t<exit, OTHER
blocks held fixed at their solution placement), then test whether there EXISTS
a crane-feasible (x,y,orient) for b:
    feasible(x,y,o) := bay.contains_block(nb) and not check_entry(bay,present,nb,fast=True)
The earliest such t gives:
    headroom_b      = entry_b - earliest        (>0 => could have entered earlier)
    tard_reducible  = min(headroom_b, exit_b - due_b)

CAVEAT (myopic): all OTHER blocks are held at their solution times/places. We do
not re-pack downstream; this is a lower bound on what a smarter decode could do
at b in isolation, and an upper bound on the per-block reduction usable without
disturbing the rest.
"""

import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from utils import Block, Bay, check_entry            # noqa: E402
from baseline_greedy import _candidate_positions, _block_bbox  # noqa: E402

INSTANCES = ["prob_6", "prob_11", "prob_14", "prob_16", "prob_20"]
INST_DIR = ROOT / "instances" / "train"
SOL_DIR = ROOT / "results" / "z1_exp_B"

MAX_SCAN_STEPS = 40        # cap inner-t scan (check_entry uses Shapely -> slow)
MAX_TARDY_PER_INST = 60    # sample largest-tardiness blocks beyond this


def load_solution_blocks(sol):
    """Reconstruct per-block records from the operations stream.

    Returns dict block_id -> {bay, x, y, orient, entry, exit}.
    Times are int(t) parsed from the operation-stream keys.
    """
    rec = {}
    for t_str, ops in sol["operations"].items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            r = rec.setdefault(bid, {})
            if op["type"] == "ENTRY":
                r["bay"] = op["bay_id"]
                r["x"] = op["x"]
                r["y"] = op["y"]
                r["orient"] = op["orient_idx"]
                r["entry"] = t
            elif op["type"] == "EXIT":
                r["exit"] = t
    return rec


def present_in_bay(rec, blocks_data, bay_id, t):
    """Build Block objects for every block present in bay_id at time t
    (entry <= t < exit), placed at its solution (x,y,orient)."""
    out = []
    for bid, r in rec.items():
        if r.get("bay") != bay_id:
            continue
        if "entry" not in r or "exit" not in r:
            continue
        if r["entry"] <= t < r["exit"]:
            out.append(Block(block_id=bid, block_data=blocks_data[bid],
                             x=r["x"], y=r["y"], orient_idx=r["orient"]))
    return out


def exists_crane_feasible(bay, present, b, blocks_data):
    """True iff SOME (x,y,orient) lets block b enter crane-feasibly given
    `present` fixed.  Uses the baseline bottom-left candidate generator per
    orientation; this is the same placement set the decoder itself searches."""
    blk = blocks_data[b]
    for oi in range(len(blk["shape"])):
        bb = _block_bbox(blk, oi)
        # quick reject: block bbox larger than bay in this orientation
        if (bb[2] - bb[0]) > bay.width + 1e-6 or (bb[3] - bb[1]) > bay.height + 1e-6:
            continue
        cands = _candidate_positions(bay.width, bay.height, present, bb)
        # always include origin as a fallback candidate
        if (0, 0) not in cands:
            cands = [(0, 0)] + cands
        for (cx, cy) in cands:
            nb = Block(block_id=b, block_data=blk, x=cx, y=cy, orient_idx=oi)
            if not bay.contains_block(nb):
                continue
            if not check_entry(bay, present, nb, fast=True):
                return True
    return False


def analyze_instance(inst_name):
    inst = json.loads((INST_DIR / f"{inst_name}.json").read_text())
    sol = json.loads((SOL_DIR / f"sol_{inst_name}__base.json").read_text())
    blocks_data = inst["blocks"]
    bays = [Bay.from_dict(d, j) for j, d in enumerate(inst["bays"])]

    rec = load_solution_blocks(sol)

    # collect tardy blocks: exit > due
    tardy = []
    for bid, r in rec.items():
        if "exit" not in r or "entry" not in r:
            continue
        due = blocks_data[bid]["due_date"]
        tard = r["exit"] - due
        if tard > 0:
            tardy.append((bid, tard))

    sampled = False
    tardy.sort(key=lambda kv: kv[1], reverse=True)
    if len(tardy) > MAX_TARDY_PER_INST:
        tardy = tardy[:MAX_TARDY_PER_INST]
        sampled = True

    n_total = len(tardy)
    n_headroom = 0
    n_crane_forced = 0
    n_earliest_at_release = 0   # diagnostic: feasible already at r_b
    n_scan_capped = 0           # diagnostic: entry_b - r_b exceeded the 40-step cap
    sum_tard_reducible = 0
    total_tard_tested = 0

    t0 = time.monotonic()
    for idx, (bid, tard) in enumerate(tardy, 1):
        r = rec[bid]
        bay = bays[r["bay"]]
        r_b = blocks_data[bid]["release_time"]
        entry_b = r["entry"]
        exit_b = r["exit"]
        due = blocks_data[bid]["due_date"]
        total_tard_tested += tard

        earliest = entry_b
        hi = min(entry_b, r_b + MAX_SCAN_STEPS)
        if entry_b > r_b + MAX_SCAN_STEPS:
            n_scan_capped += 1
        for t in range(r_b, hi):
            present = present_in_bay(rec, blocks_data, r["bay"], t)
            # b itself must not be in `present` (it is excluded since we scan t < entry_b)
            if exists_crane_feasible(bay, present, bid, blocks_data):
                earliest = t
                if t == r_b:
                    n_earliest_at_release += 1
                break

        headroom = entry_b - earliest
        if headroom > 0:
            n_headroom += 1
        else:
            n_crane_forced += 1
        sum_tard_reducible += min(headroom, exit_b - due)

        if idx % 10 == 0 or idx == n_total:
            print(f"  [{inst_name}] {idx}/{n_total} tardy processed "
                  f"({time.monotonic()-t0:.1f}s)", flush=True)

    pct_blocks_with_headroom = (100.0 * n_headroom / n_total) if n_total else 0.0
    pct_Z1_reducible = (100.0 * sum_tard_reducible / total_tard_tested) if total_tard_tested else 0.0

    return {
        "inst": inst_name,
        "tardy_tested": n_total,
        "n_headroom": n_headroom,
        "n_crane_forced": n_crane_forced,
        "pct_blocks_with_headroom": pct_blocks_with_headroom,
        "sum_tard_reducible": sum_tard_reducible,
        "total_tardiness_of_tested": total_tard_tested,
        "pct_Z1_reducible": pct_Z1_reducible,
        "sampled": sampled,
        "n_earliest_at_release": n_earliest_at_release,
        "n_scan_capped": n_scan_capped,
    }


def main():
    results = []
    for inst_name in INSTANCES:
        print(f"== analyzing {inst_name} ==", flush=True)
        results.append(analyze_instance(inst_name))

    # ---- table ----
    hdr = ["inst", "tardy_tested", "n_headroom", "n_crane_forced",
           "pct_blk_hr", "sum_tard_red", "tot_tard", "pct_Z1_red", "sampled"]
    widths = [8, 12, 10, 14, 10, 12, 9, 10, 7]

    def fmt_row(vals):
        return " | ".join(str(v).rjust(w) for v, w in zip(vals, widths))

    print("\n" + "=" * 110)
    print("CRANE-HEADROOM ANALYSIS (base solutions)")
    print("=" * 110)
    print(fmt_row(hdr))
    print("-" * 110)
    for r in results:
        print(fmt_row([
            r["inst"], r["tardy_tested"], r["n_headroom"], r["n_crane_forced"],
            f'{r["pct_blocks_with_headroom"]:.1f}', r["sum_tard_reducible"],
            r["total_tardiness_of_tested"], f'{r["pct_Z1_reducible"]:.1f}',
            "Y" if r["sampled"] else "-",
        ]))
    print("=" * 110)

    # aggregate
    tot_red = sum(r["sum_tard_reducible"] for r in results)
    tot_tard = sum(r["total_tardiness_of_tested"] for r in results)
    agg_pct = 100.0 * tot_red / tot_tard if tot_tard else 0.0
    print(f"\nAGGREGATE: sum_tard_reducible={tot_red}  total_tardiness_tested={tot_tard}  "
          f"pct_Z1_reducible={agg_pct:.1f}%")

    # diagnostic: how much of the headroom is "feasible already at release time"
    print("\nDIAGNOSTIC (myopic-caveat strength):")
    print(f"{'inst':>8} | {'feasible@release':>16} | {'scan-capped(>40)':>16}  "
          f"(of tardy_tested)")
    for r in results:
        print(f"{r['inst']:>8} | {r['n_earliest_at_release']:>16} | "
              f"{r['n_scan_capped']:>16}  / {r['tardy_tested']}")
    print("  feasible@release: block fits at its OWN release time when other blocks "
          "are held fixed -> headroom is real but myopic (bay emptier at r_b).")
    return results


if __name__ == "__main__":
    main()
