#!/usr/bin/env python3
"""
validate_clean_decode.py -- DECISIVE, READ-ONLY validation.

Question
--------
Does a CLEAN (untruncated) per-bay decode of prob_6's EXISTING block->bay
assignment yield a solution that the OFFICIAL checker (utils.check_feasibility)
accepts as FEASIBLE, with a dramatically lower Z1 (obj1) -- or is the headroom
an artifact of an optimistic internal decode?

We measured ~99% per-bay Z1 reduction from a clean standalone decode, and the
resequence_gain self-check showed the BASE solution's own exits are far worse
than a clean standalone decode -> the full solver budget-truncates large bays
and force-places blocks late.  This script PROVES (or disproves) feasibility of
the clean decode under the official checker.

Mechanism (reused EXACTLY from tools/resequence_gain.py)
-------------------------------------------------------
- import _decode_bay, _orderings, _bay_tardiness from myalgorithm
- import Bay, check_feasibility from utils
- group blocks by their base-solution-assigned bay
- per bay, decode cleanly (deadline=None => NO budget truncation) using the
  min-tardiness ordering among _orderings outputs (EDD/REL/ATCR)
- assemble full official-format solution, run check_feasibility

READ-ONLY w.r.t. utils.py / baseline / myalgorithm.py -- imports only.
"""

import os
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Same env switches resequence_gain.py uses: ATCR seed on, crane-safe decode on.
os.environ.setdefault("OGC_ATCR_SEED", "1")
os.environ.setdefault("OGC_CRANE_SAFE", "1")

from utils import Bay, check_feasibility                              # noqa: E402
from myalgorithm import _decode_bay, _orderings, _bay_tardiness       # noqa: E402

INST_PATH = ROOT / "instances" / "train" / "prob_6.json"
SOL_PATH = ROOT / "results" / "z1_exp_B" / "sol_prob_6__base.json"
SCORE_PATH = ROOT / "results" / "z1_exp_B" / "score_prob_6__base.json"
OUT_PATH = ROOT / "results" / "clean_decode_prob6.json"
PLACE_PATH = ROOT / "results" / "clean_decode_prob6_placements.json"


def load_solution_blocks(sol):
    """block_id -> {bay, x, y, orient, entry, exit} from the operations stream."""
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


def clean_decode_bay(bay, bay_idx, ids, blocks_data):
    """Clean (deadline=None => NO truncation) decode for one bay.

    Try every ordering from _orderings (EDD/REL/ATCR); pick the one with the
    minimum bay tardiness.  Returns (best_result_dict, best_tard, label, n_forced).
    """
    best_res = None
    best_tard = float("inf")
    best_label = None
    best_forced = None
    for lab, order in zip(("EDD", "REL", "ATCR"),
                          _orderings(list(ids), blocks_data, allow_alt=True)):
        # deadline=None => clean/full crane-safe decode, no budget truncation.
        res, forced = _decode_bay(bay, bay_idx, list(order), blocks_data, deadline=None)
        if res is None:
            continue
        t = _bay_tardiness(res, blocks_data)
        if t < best_tard:
            best_tard = t
            best_res = res
            best_label = lab
            best_forced = forced
    return best_res, best_tard, best_label, (len(best_forced) if best_forced else 0)


def results_to_placements(per_bay_results):
    """Flatten decode results into per-block placement records.

    Returns block_id -> {bay, x, y, orient, entry, exit} (the same schema as
    load_solution_blocks).  This is the single source of truth that both
    assemble_solution and the tied-exit repair operate on.
    """
    rec = {}
    for res in per_bay_results:
        for a in res.values():
            rec[int(a["block_id"])] = {
                "bay": int(a["bay_id"]),
                "x": int(a["x"]),
                "y": int(a["y"]),
                "orient": int(a["orient_idx"]),
                "entry": int(a["entry_time"]),
                "exit": int(a["exit_time"]),
            }
    return rec


def assemble_from_placements(placements):
    """Build official-format {"operations": {str(t): [op,...]}} from per-block
    placement records (block_id -> {bay,x,y,orient,entry,exit}).

    Two ordering rules the official checker REQUIRES (both discovered the hard
    way during this validation -- without them the assembled dict is not even a
    well-formed official solution):
      (1) time keys must be inserted in ASCENDING integer-time order.  The
          checker parses operations in dict-insertion order and matches an EXIT
          to its block only if the block's ENTRY was already seen
          (utils.py:1078).  If an EXIT key is inserted before its ENTRY key the
          checker reports "block X has no EXIT operation" (a false Stage-1
          failure that is purely a serialisation artifact).
      (2) within a single time point, EXIT ops must precede ENTRY ops
          (Stage-5: "EXIT must precede ENTRY").
    """
    flat = []  # (time, exit_first_priority, op)
    for bid, a in placements.items():
        flat.append((a["entry"], 1, {
            "type": "ENTRY",
            "block_id": int(bid),
            "bay_id": int(a["bay"]),
            "x": int(a["x"]),
            "y": int(a["y"]),
            "orient_idx": int(a["orient"]),
        }))
        flat.append((a["exit"], 0, {
            "type": "EXIT",
            "block_id": int(bid),
            "bay_id": int(a["bay"]),
        }))
    ops = {}
    for t, _pri, op in sorted(flat, key=lambda e: (e[0], e[1])):
        ops.setdefault(str(int(t)), []).append(op)
    return {"operations": ops}


def separate_tied_exits(placements, blocks_data):
    """TIED-EXIT SEPARATION repair (in-place on a copy).

    Within each bay, find groups of blocks that share the same exit_time.  For
    each tied group the official sweep-check flags simultaneous EXITs in the same
    bay as a collision (Stage5 "obstructed by ... (sweep)").  We keep ONE block
    at the original tick -- the one with the EARLIEST due_date (it is the most
    urgent / least slack, so it should not be pushed later) -- and bump the
    others to the minimal DISTINCT LATER ticks (exit+1, +2, ...) that are not
    already used as an exit_time by another block in the same bay.

    Only moving exits LATER keeps EXIT - ENTRY >= processing_time satisfied
    (entries are untouched).  Returns (new_placements, stats) where stats =
    {bay -> {"groups": g, "bumped": b}} and totals.
    """
    new = {bid: dict(a) for bid, a in placements.items()}

    # bay -> {exit_time -> [block_id, ...]}
    by_bay = {}
    for bid, a in new.items():
        by_bay.setdefault(a["bay"], {}).setdefault(a["exit"], []).append(bid)

    stats = {}
    total_groups = 0
    total_bumped = 0
    for bay, by_exit in by_bay.items():
        used = set(by_exit.keys())          # exit ticks already occupied in this bay
        groups = 0
        bumped = 0
        for t in sorted(by_exit):
            grp = by_exit[t]
            if len(grp) < 2:
                continue
            groups += 1
            # keep the earliest-due block at t; bump the rest to later free ticks.
            grp_sorted = sorted(grp, key=lambda b: blocks_data[b]["due_date"])
            keep = grp_sorted[0]            # earliest due_date stays
            nxt = t + 1
            for bid in grp_sorted[1:]:
                while nxt in used:
                    nxt += 1
                new[bid]["exit"] = nxt
                used.add(nxt)
                bumped += 1
                nxt += 1
        if groups or bumped:
            stats[bay] = {"groups": groups, "bumped": bumped}
        total_groups += groups
        total_bumped += bumped
    stats["_total"] = {"groups": total_groups, "bumped": total_bumped}
    return new, stats


def z1_of(placements, blocks_data):
    """Sum of tardiness = sum max(0, exit - due_date) over all placed blocks.

    Matches the official Z1 definition; used only for the informational note
    about how much Z1 rose after the tied-exit bumps (the authoritative numbers
    still come from check_feasibility)."""
    z = 0
    for bid, a in placements.items():
        z += max(0, a["exit"] - blocks_data[bid]["due_date"])
    return z


def fmt_r(r):
    return (f"feasible={r['feasible']} stage={r['stage']} "
            f"obj1={r['obj1']} obj2={r['obj2']} obj3={r['obj3']} "
            f"objective={r['objective']}")


def main():
    prob_info = json.loads(INST_PATH.read_text())
    base_sol = json.loads(SOL_PATH.read_text())
    score = json.loads(SCORE_PATH.read_text())
    blocks_data = prob_info["blocks"]
    bays = [Bay.from_dict(d, j) for j, d in enumerate(prob_info["bays"])]

    print("=" * 78)
    print("STEP 1 -- SANITY: does check_feasibility reproduce the BASE score file?")
    print("=" * 78)
    rb = check_feasibility(prob_info, base_sol)
    print("  base checker :", fmt_r(rb))
    print(f"  score file   : feasible={score['feasible']} stage={score['stage']} "
          f"obj1={score['obj1']} obj2={score['obj2']} obj3={score['obj3']} "
          f"objective={score['objective']}")

    def close(a, b, tol=1.0):
        return a is not None and b is not None and abs(float(a) - float(b)) <= tol

    sanity_ok = (
        bool(rb["feasible"]) is True
        and close(rb["obj1"], score["obj1"])
        and close(rb["obj2"], score["obj2"])
        and close(rb["obj3"], score["obj3"])
        and close(rb["objective"], score["objective"], tol=max(10.0, abs(score["objective"]) * 1e-6))
    )
    if not sanity_ok:
        print("\n  SANITY CHECK FAILED -- checker does not reproduce the base score.")
        print("  The checker call/format is wrong; nothing downstream is trustworthy.")
        print("  STOPPING.")
        if rb["violations"]:
            print("  first violations:", rb["violations"][:5])
        return
    print("  SANITY OK -- checker reproduces base score within tolerance.\n")

    print("=" * 78)
    print("STEP 2/3 -- CLEAN (untruncated) per-bay decode of the base assignment")
    print("=" * 78)
    rec = load_solution_blocks(base_sol)
    by_bay = {}
    for bid, r in rec.items():
        if "bay" not in r:
            continue
        by_bay.setdefault(r["bay"], []).append(bid)

    t0 = time.monotonic()
    per_bay_results = []
    total_forced = 0
    decode_failed = False
    for bay_idx in sorted(by_bay):
        ids = by_bay[bay_idx]
        bt0 = time.monotonic()
        res, tard, label, n_forced = clean_decode_bay(bays[bay_idx], bay_idx, ids, blocks_data)
        if res is None:
            print(f"  bay {bay_idx} (n={len(ids)}): DECODE FAILED -- a block cannot fit.")
            decode_failed = True
            break
        total_forced += n_forced
        per_bay_results.append(res)
        print(f"  bay {bay_idx} (n={len(ids):3d}): tard={tard:>10.0f} "
              f"win={label:4s} forced={n_forced:3d} "
              f"({time.monotonic()-bt0:.1f}s)", flush=True)
    decode_wall = time.monotonic() - t0
    print(f"  clean-decode wall-time: {decode_wall:.1f}s  (force-placed blocks: {total_forced})")

    if decode_failed:
        print("\n  Clean decode could not place all blocks -> cannot assemble a solution.")
        print("  BOTTOM LINE: headroom is ILLUSORY for this assignment (decode infeasible).")
        return

    # ---- flatten to per-block placements; ALWAYS save the clean artifacts ----
    clean_placements = results_to_placements(per_bay_results)
    clean_sol = assemble_from_placements(clean_placements)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(clean_sol))
    PLACE_PATH.write_text(json.dumps(
        {str(bid): a for bid, a in sorted(clean_placements.items())}, indent=0))
    print(f"\nSAVED clean solution           -> {OUT_PATH}")
    print(f"SAVED clean per-block placements -> {PLACE_PATH}")
    clean_z1_local = z1_of(clean_placements, blocks_data)
    print(f"  (clean local Z1 = sum tardiness = {clean_z1_local})")

    print("\n" + "=" * 78)
    print("STEP 4 -- OFFICIAL VERDICT on the assembled clean solution (UNREPAIRED)")
    print("=" * 78)
    rc = check_feasibility(prob_info, clean_sol)
    print("  clean checker:", fmt_r(rc))
    if not rc["feasible"]:
        print(f"  n_violations: {len(rc['violations'])}  (failed at stage {rc['stage']})")
        for v in rc["violations"][:5]:
            print("    -", v)

    # ----------------------------------------------------------------------
    # STEP 5 -- TIED-EXIT SEPARATION repair + RE-CHECK
    # ----------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("STEP 5 -- TIED-EXIT SEPARATION repair, then OFFICIAL re-check")
    print("=" * 78)
    rep_placements, sep_stats = separate_tied_exits(clean_placements, blocks_data)
    tot = sep_stats.pop("_total")
    print("  tied-exit groups / bumped blocks per bay (bays with any tie):")
    if sep_stats:
        for bay in sorted(sep_stats):
            s = sep_stats[bay]
            print(f"    bay {bay:3d}: groups={s['groups']:3d}  bumped={s['bumped']:3d}")
    else:
        print("    (none -- no two blocks in any bay shared an exit_time)")
    print(f"  TOTAL tied-exit groups: {tot['groups']}   "
          f"blocks bumped later: {tot['bumped']}")

    rep_sol = assemble_from_placements(rep_placements)
    rep_z1_local = z1_of(rep_placements, blocks_data)
    print(f"  local Z1 (sum tardiness): clean={clean_z1_local} -> "
          f"repaired={rep_z1_local}  (+{rep_z1_local - clean_z1_local})")

    rr = check_feasibility(prob_info, rep_sol)
    print("\n  repaired checker:", fmt_r(rr))
    if not rr["feasible"]:
        print(f"  n_violations: {len(rr['violations'])}  (failed at stage {rr['stage']})")
        for v in rr["violations"][:5]:
            print("    -", v)
    # persist the repaired solution too (cheap, and it is the candidate of record)
    REP_PATH = OUT_PATH.with_name("clean_decode_prob6_tiesep.json")
    REP_PATH.write_text(json.dumps(rep_sol))
    print(f"  SAVED repaired (tie-separated) solution -> {REP_PATH}")

    # ----------------------------------------------------------------------
    # STEP 6 -- COMPARE base vs repaired-clean
    # ----------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("STEP 6 -- COMPARE base vs repaired-clean (tie-separated)")
    print("=" * 78)
    print(f"{'':14s} | {'feasible':>8} | {'Z1(obj1)':>12} | {'obj2':>8} | "
          f"{'obj3':>8} | {'objective':>14}")
    print("-" * 78)
    print(f"{'base':14s} | {str(rb['feasible']):>8} | {rb['obj1']:>12.0f} | "
          f"{rb['obj2']:>8.0f} | {rb['obj3']:>8.0f} | {rb['objective']:>14.0f}")
    if rr["feasible"]:
        print(f"{'repaired-clean':14s} | {str(rr['feasible']):>8} | {rr['obj1']:>12.0f} | "
              f"{rr['obj2']:>8.0f} | {rr['obj3']:>8.0f} | {rr['objective']:>14.0f}")
    else:
        print(f"{'repaired-clean':14s} | {str(rr['feasible']):>8} | "
              f"(INFEASIBLE stage {rr['stage']} -- no objective)")

    print("=" * 78)
    if rr["feasible"]:
        z1_red = rb["obj1"] - rr["obj1"]
        z1_pct = (100.0 * z1_red / rb["obj1"]) if rb["obj1"] else 0.0
        obj_red = rb["objective"] - rr["objective"]
        obj_pct = (100.0 * obj_red / rb["objective"]) if rb["objective"] else 0.0
        d2 = rr["obj2"] - rb["obj2"]
        d3 = rr["obj3"] - rb["obj3"]
        print(f"Z1 reduction : {z1_red:.0f}  ({z1_pct:.1f}%)")
        print(f"objective red: {obj_red:.0f}  ({obj_pct:.1f}%)")
        print(f"obj2 delta   : {d2:+.0f}   obj3 delta: {d3:+.0f}  "
              f"(expected ~0: same block->bay assignment)")
        if abs(d2) > 1e-6 or abs(d3) > 1e-6:
            print("  NOTE: obj2/obj3 changed -- they depend ONLY on the (unchanged)")
            print("  block->bay assignment, so a nonzero delta means a block landed in a")
            print("  different bay or was dropped -- INSPECT.")
        print("\nBOTTOM LINE: separating tied exit-times made the clean decode")
        print("officially FEASIBLE.  => the ~99% Z1 headroom is REAL; the root cause of")
        print("the lone Stage-5 violation was the SIMULTANEOUS-EXIT crane-model gap")
        print("(the solver's decoder is looser than the official sweep check on")
        print("equal-time exits in the same bay).")
    else:
        # honest negative report: identify whether the surviving violation is
        # still a tie/sweep issue or something deeper.
        first = rr["violations"][0] if rr["violations"] else "(none recorded)"
        print(f"Z1 reduction : (n/a -- repaired solution still INFEASIBLE)")
        print(f"first surviving violation: {first}")
        print("\nBOTTOM LINE: separating tied exit-times did NOT make the clean decode")
        print("officially feasible.  => the gap is DEEPER than simultaneous-EXIT ties;")
        print("the remaining violation(s) above are the real obstacle, and the ~99% Z1")
        print("headroom is NOT yet realizable by tie-separation alone.  Be honest: this")
        print("needs a decoder/crane-model fix beyond reshuffling equal exit ticks.")

    print("\n" + "=" * 78)
    print(f"  decode wall-time: {decode_wall:.1f}s (run once, reused for both checks).")
    print("=" * 78)


if __name__ == "__main__":
    main()
