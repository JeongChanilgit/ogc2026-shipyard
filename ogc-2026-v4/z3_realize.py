"""
z3_realize.py -- z3 area-neutral reassignment REALIZE test.

Does the area-neutral CP-SAT assignment (from z3_headroom.py) actually lower
the FULL obj when executed, or does z1 blow up and wipe out the z3 gain?

Pipeline per instance:
  1. Load real_prob_N.json (current solution) -> base obj/z1/z3.
  2. Run area-neutral CP-SAT assignment (exact block count + per-bay area ±10%,
     minimize z3).  Re-use z3_headroom._solve_assignment_areaneutral.
  3. Build per-bay placed lists:
       a. For bays UNCHANGED by the reassignment: keep current placed records.
       b. For bays with ANY reassigned blocks:
            seed reassigned blocks into the bay (via bpass._seed_into_bay),
            then call crane_repack_bay(free_ids=reassigned_in_bay) -- existing
            blocks stay frozen, only the incoming blocks are repositioned.
  4. global_eval -> realized obj/z1/z2/z3, feasible.
     Never-worse gate: accept if feasible AND realized_obj < base_obj - 1e-6.
  5. Partial fallback: if full reassignment fails or regresses, try assigning
     only the TOP-K blocks (by z3 reduction, greedily) and re-packing just
     those bays.  K steps: K = n_changed//2, n_changed//4, 5, 1.

Target instances (z3-heavy from user brief):
    prob_31, prob_28, prob_35 (primary)
    prob_24, prob_36 (secondary)

Run:
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe z3_realize.py
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe z3_realize.py 31,28,35
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe z3_realize.py 31 --partial
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from copy import deepcopy

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

# crane_cpsat is in v4 dir
import crane_cpsat as _crane          # noqa: E402
import adapter as _adapter            # noqa: E402
import seed as _seed                  # noqa: E402
import bpass as _bpass                # noqa: E402
import utils as _utils                # noqa: E402

from z3_headroom import (             # noqa: E402
    _solve_assignment_areaneutral,
    _parse_solution,
    _footprint_area as _headroom_area,
)

INST_DIR = os.path.normpath(os.path.join(THIS, "..", "instances", "train"))
ASSIGN_TL = 20.0    # CP-SAT assignment wall (s)
REPACK_TL = 60.0    # crane_repack_bay wall per bay (s)
INSTANCE_BUDGET = 180.0  # max wall per instance (s)

DEFAULT_PROBS = [31, 28, 35, 24, 36]

# ---------------------------------------------------------------------------
# Helper: z3 contribution of one block in a given bay
# ---------------------------------------------------------------------------
def _z3_contrib(data: dict, bid: int, bay: int) -> float:
    prefs = data["blocks"][bid]["bay_preferences"]
    return float(max(prefs) - prefs[bay])


# ---------------------------------------------------------------------------
# Core realize function
# ---------------------------------------------------------------------------
def realize_instance(prob_num: int, partial: bool = False,
                     time_budget: float = INSTANCE_BUDGET) -> dict:
    """Full area-neutral z3 realize for one instance.

    Returns a result dict with keys:
        prob, base_obj, base_z1, base_z3,
        assign_z3 (area-neutral assignment z3), assign_status,
        n_changed (blocks moved to different bay),
        realized_obj, realized_z1, realized_z3, realized_feasible,
        delta_obj, delta_z1, delta_z3,
        accepted (bool: realized_obj < base_obj),
        partial_k (int: how many blocks used in partial fallback, None if full),
        wall (s)
    """
    t_start = time.monotonic()

    inst_path = os.path.join(INST_DIR, f"prob_{prob_num}.json")
    sol_path = os.path.join(THIS, f"real_prob_{prob_num}.json")

    data = json.load(open(inst_path, encoding="utf-8"))
    sol = json.load(open(sol_path, encoding="utf-8"))
    w = data.get("weights", {})
    w1 = float(w.get("w1", 1.0))
    w3 = float(w.get("w3", 1.0))

    # --- (1) current base ---------------------------------------------------
    base_chk = _utils.check_feasibility(data, sol)
    base_obj = float(base_chk.get("objective", 0) or 0)
    base_z1 = float(base_chk.get("obj1", 0) or 0)
    base_z3 = float(base_chk.get("obj3", 0) or 0)

    # Reconstruct placed records from current solution
    bays_placed_cur = _adapter.deserialize(data, sol, scale=2)

    # Parse solution for area-neutral assignment model
    cur_bay, cur_orient, cur_entry, cur_exit, pref_bay, tardiness = \
        _parse_solution(data, sol)

    # --- (2) area-neutral CP-SAT assignment ---------------------------------
    t_assign = time.monotonic()
    assign_z3, assign_status, new_assign = _solve_assignment_areaneutral(
        data, cur_bay, cur_orient, time_s=ASSIGN_TL)

    if new_assign is None:
        return {
            "prob": prob_num, "base_obj": base_obj, "base_z1": base_z1,
            "base_z3": base_z3, "assign_z3": None, "assign_status": assign_status,
            "n_changed": 0, "realized_obj": None, "realized_z1": None,
            "realized_z3": None, "realized_feasible": False,
            "delta_obj": None, "delta_z1": None, "delta_z3": None,
            "accepted": False, "partial_k": None,
            "wall": time.monotonic() - t_start,
            "error": f"assignment-{assign_status}",
        }

    # Identify changed blocks {bid: (old_bay, new_bay)}
    changed = {
        bid: (cur_bay[bid], new_assign[bid])
        for bid in cur_bay
        if new_assign.get(bid, cur_bay[bid]) != cur_bay[bid]
    }
    n_changed = len(changed)

    # Sort changed blocks by z3 gain (largest first) for partial fallback
    def _z3_gain(bid):
        old_j, new_j = changed[bid]
        return _z3_contrib(data, bid, old_j) - _z3_contrib(data, bid, new_j)
    changed_sorted = sorted(changed.keys(), key=_z3_gain, reverse=True)

    # --- (3) build realized placement ---------------------------------------
    def _try_k_changes(k_bids):
        """Try applying a specific set of block-id changes.
        Returns (bays_placed_trial, n_applied) or (None, 0) on failure.
        """
        # Build the effective assignment for only k_bids changes
        effective_new = dict(cur_bay)  # start from current
        for bid in k_bids:
            effective_new[bid] = new_assign[bid]

        # Which bays are affected (have any block moved in OR out)?
        affected_bays = set()
        for bid in k_bids:
            old_j, new_j = cur_bay[bid], new_assign[bid]
            affected_bays.add(old_j)
            affected_bays.add(new_j)

        # Group all blocks by their effective new bay
        by_new_bay: dict[int, list] = {}
        for bid, bj in effective_new.items():
            by_new_bay.setdefault(bj, []).append(bid)

        # Build trial placed dict: unaffected bays copied, affected bays repacked
        trial = dict(bays_placed_cur)  # shallow copy

        for j in affected_bays:
            # Get current placed records in bay j (before any changes)
            placed_j_cur = list(bays_placed_cur.get(j, []))

            # Blocks that STAY in bay j (not moved out)
            staying = {p["id"] for p in placed_j_cur
                       if effective_new.get(p["id"], cur_bay.get(p["id"], -1)) == j}
            # Blocks that ARRIVE from another bay
            arriving = {bid for bid, (old_j, new_j) in changed.items()
                        if bid in k_bids and new_j == j and old_j != j}

            # Placed list = frozen (staying) + seeded (arriving)
            placed_j_frozen = [p for p in placed_j_cur if p["id"] in staying]

            if not arriving:
                # No new arrivals -- just remove the blocks that left
                trial[j] = placed_j_frozen
                continue

            # Seed incoming blocks into bay j using bpass._seed_into_bay
            seeded = []
            for bid in arriving:
                # Find the placed record in the block's original bay
                old_j_bay = cur_bay[bid]
                orig_pb = next(
                    (p for p in bays_placed_cur.get(old_j_bay, [])
                     if p["id"] == bid),
                    None
                )
                if orig_pb is None:
                    return None, 0  # can't find block record
                try:
                    seed_rec = _bpass._seed_into_bay(data, j, orig_pb)
                    seeded.append(seed_rec)
                except Exception:
                    return None, 0

            # crane_repack_bay: freeze staying blocks, free only arriving
            placed_j_trial = placed_j_frozen + seeded
            free_ids = set(arriving)

            budget_remaining = max(5.0, time_budget - (time.monotonic() - t_start))
            bay_tl = min(REPACK_TL, budget_remaining)

            try:
                new_j_placed, status, wall, cinfo = _crane.crane_repack_bay(
                    data, j, placed_j_trial, bay_tl,
                    n_xcand=5, n_ycand=0, n_ocand=0,
                    free_ids=free_ids)
            except Exception as exc:
                # CP-SAT model build can fail on huge bays
                return None, 0

            if new_j_placed is None:
                return None, 0

            trial[j] = new_j_placed

        return trial, len(k_bids)

    # --- (4) full reassignment attempt --------------------------------------
    result_trial = None
    partial_k = None

    if time.monotonic() - t_start < time_budget - 5:
        result_trial, n_applied = _try_k_changes(changed_sorted)

    # --- (5) partial fallback if full fails or not requested ----------------
    if result_trial is None and (partial or True):  # always try partial
        # Fallback cascade: K = n_changed//2, n_changed//4, 10, 5, 1
        fallback_ks = []
        for divisor in [2, 4]:
            k = max(1, n_changed // divisor)
            if k < n_changed:
                fallback_ks.append(k)
        for k in [10, 5, 1]:
            if k < n_changed:
                fallback_ks.append(k)
        fallback_ks = sorted(set(fallback_ks), reverse=True)

        for k in fallback_ks:
            if time.monotonic() - t_start >= time_budget - 5:
                break
            trial_k, n_k = _try_k_changes(changed_sorted[:k])
            if trial_k is not None:
                result_trial = trial_k
                partial_k = k
                break

    # --- (6) evaluate realized solution -------------------------------------
    if result_trial is None:
        return {
            "prob": prob_num, "base_obj": base_obj, "base_z1": base_z1,
            "base_z3": base_z3, "assign_z3": assign_z3,
            "assign_status": assign_status,
            "n_changed": n_changed, "realized_obj": None,
            "realized_z1": None, "realized_z3": None,
            "realized_feasible": False,
            "delta_obj": None, "delta_z1": None, "delta_z3": None,
            "accepted": False, "partial_k": partial_k,
            "wall": time.monotonic() - t_start,
            "error": "repack-failed",
        }

    ev = _seed.global_eval(data, result_trial)
    r_obj = float(ev["obj"] or 0)
    r_z1 = float(ev["z1"] or 0)
    r_z3 = float(ev["z3"] or 0)
    r_feas = bool(ev["feasible"])

    delta_obj = r_obj - base_obj
    delta_z1 = r_z1 - base_z1
    delta_z3 = r_z3 - base_z3
    accepted = r_feas and r_obj < base_obj - 1e-6

    return {
        "prob": prob_num,
        "w1": w1, "w3": w3,
        "base_obj": base_obj, "base_z1": base_z1, "base_z3": base_z3,
        "assign_z3": assign_z3, "assign_status": assign_status,
        "n_changed": n_changed, "n_applied": n_applied if result_trial is not None else 0,
        "realized_obj": r_obj, "realized_z1": r_z1,
        "realized_z3": r_z3, "realized_feasible": r_feas,
        "delta_obj": delta_obj, "delta_z1": delta_z1, "delta_z3": delta_z3,
        "delta_obj_pct": 100.0 * delta_obj / base_obj if base_obj else 0,
        "accepted": accepted,
        "partial_k": partial_k,
        "wall": time.monotonic() - t_start,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _fmt(v, decimals=0):
    if v is None:
        return "--"
    if decimals == 0:
        return f"{int(round(v)):,}"
    return f"{v:.{decimals}f}"


def _sign(v):
    if v is None:
        return "--"
    return f"{v:+,.0f}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    partial = "--partial" in sys.argv

    if arg and not arg.startswith("--"):
        probs = [int(x) for x in arg.split(",") if x.strip().isdigit()]
    else:
        probs = list(DEFAULT_PROBS)

    print("=" * 130)
    print("z3 REALIZE TEST -- area-neutral reassignment -> crane_repack_bay -> official obj")
    print("  Verifies: does assignment-level z3 recovery survive repacking? "
          "(area-neutral proxy z1-safe?)")
    print("=" * 130)
    hdr = (
        f"{'p':>4} | {'base_obj':>13} | {'real_obj':>13} | "
        f"{'Δobj':>10} | {'Δobj%':>6} | "
        f"{'Δz1':>9} | {'Δz3':>9} | "
        f"{'chg':>5} | {'feas':>4} | {'acc':>3} | "
        f"{'wall':>6} | notes"
    )
    print(hdr)
    print("-" * 130)

    rows = []
    for p in probs:
        print(f"  [prob_{p}] running...", flush=True)
        res = realize_instance(p, partial=partial)
        rows.append(res)

        notes = []
        if res.get("partial_k") is not None:
            notes.append(f"partial-K={res['partial_k']}")
        if res.get("error"):
            notes.append(res["error"])
        if res.get("assign_status"):
            notes.append(f"assign={res['assign_status']}")
        notes_str = " ".join(notes) or "full"

        print(
            f"{p:>4} | {_fmt(res['base_obj']):>13} | "
            f"{_fmt(res.get('realized_obj')):>13} | "
            f"{_sign(res.get('delta_obj')):>10} | "
            f"{_fmt(res.get('delta_obj_pct'), 1) + '%' if res.get('delta_obj_pct') is not None else '--':>6} | "
            f"{_sign(res.get('delta_z1')):>9} | "
            f"{_sign(res.get('delta_z3')):>9} | "
            f"{res.get('n_changed', 0):>5} | "
            f"{'Y' if res.get('realized_feasible') else 'N':>4} | "
            f"{'YES' if res.get('accepted') else 'no':>3} | "
            f"{res.get('wall', 0):>5.1f}s | {notes_str}",
            flush=True
        )

    print("-" * 130)

    # Summary
    accepted_rows = [r for r in rows if r.get("accepted")]
    feasible_rows = [r for r in rows if r.get("realized_feasible")]
    regression_rows = [r for r in rows
                       if r.get("realized_feasible") and r.get("delta_obj", 0) > 1e-6]

    print()
    print("=" * 130)
    print("VERDICT: z3 area-neutral assignment + crane_repack_bay -> full obj")
    print()

    for r in rows:
        p = r["prob"]
        if r.get("error") and not r.get("realized_obj"):
            print(f"  prob_{p}: FAILED ({r['error']})")
            continue
        dobj = r.get("delta_obj")
        dz1 = r.get("delta_z1")
        dz3 = r.get("delta_z3")
        feas = r.get("realized_feasible")
        acc = r.get("accepted")
        pk = r.get("partial_k")
        scope = f"partial-K={pk}" if pk is not None else "full"
        if not feas:
            verdict = "INFEASIBLE after repack"
        elif dobj is None:
            verdict = "eval-error"
        elif dobj < -1e-6:
            verdict = f"NET IMPROVEMENT ({scope}) Δobj={dobj:+,.0f}"
        elif dobj > 1e-6:
            verdict = f"z1 BLEW UP Δobj={dobj:+,.0f} (Δz1={dz1:+,.0f}, Δz3={dz3:+,.0f})"
        else:
            verdict = "neutral (no change)"

        print(f"  prob_{p}: {verdict}  "
              f"[z3: {_fmt(r['base_z3'])} -> {_fmt(r.get('realized_z3'))}  "
              f"z1: {_fmt(r['base_z1'])} -> {_fmt(r.get('realized_z1'))}  "
              f"area-neutral assign z3={_fmt(r.get('assign_z3'))}]")

    print()
    n_accept = len(accepted_rows)
    n_feas = len(feasible_rows)
    n_regress = len(regression_rows)
    n_tried = len([r for r in rows if r.get("realized_obj") is not None])

    print(f"  Instances tried: {n_tried}/{len(rows)}  "
          f"Feasible: {n_feas}  Accepted (net improve): {n_accept}  "
          f"Regression (feasible but worse): {n_regress}")

    if accepted_rows:
        total_gain = sum(r["delta_obj"] for r in accepted_rows)
        print(f"  Total obj gain on accepted instances: {total_gain:+,.0f}")
    else:
        print("  No accepted improvements => area-neutral proxy DOES NOT reliably "
              "survive full repack.")

    # z1 change analysis (is area-neutral really z1-preserving?)
    valid_z1_delta = [r for r in rows if r.get("delta_z1") is not None]
    if valid_z1_delta:
        max_z1_change = max(abs(r["delta_z1"]) for r in valid_z1_delta)
        avg_z1_change = sum(r["delta_z1"] for r in valid_z1_delta) / len(valid_z1_delta)
        print()
        print(f"  z1 change analysis (area-neutral proxy validation):")
        print(f"    max |Δz1| = {max_z1_change:,.0f}  "
              f"avg Δz1 = {avg_z1_change:+,.1f}")
        z1_explosions = [r for r in valid_z1_delta if r["delta_z1"] > 100]
        if z1_explosions:
            print(f"    z1 EXPLOSIONS (Δz1>100): "
                  + ", ".join(f"prob_{r['prob']} +{r['delta_z1']:,.0f}"
                               for r in z1_explosions))
            print("    => area-neutral PROXY IS BROKEN for these (shape mismatch)")
        else:
            z1_large = [r for r in valid_z1_delta if abs(r["delta_z1"]) > 20]
            if z1_large:
                print(f"    Notable z1 shifts: "
                      + ", ".join(f"prob_{r['prob']} {r['delta_z1']:+,.0f}"
                                   for r in z1_large))
            else:
                print("    z1 well-preserved => area-neutral proxy works geometrically")

    print()
    if n_accept > 0:
        print("  FINAL VERDICT: z3 IS a real lever (area-neutral realize works, "
              "net obj improves).")
    elif n_regress == n_feas and n_feas > 0:
        print("  FINAL VERDICT: z3 HEADROOM IS MIRAGE -- z1 always blows up during "
              "repack despite area-neutral constraint (shape mismatch / crane serialization).")
    elif n_feas == 0:
        print("  FINAL VERDICT: INFEASIBLE in all repacks -- "
              "area-neutral assignment produces geometrically impossible packing.")
    else:
        print("  FINAL VERDICT: MIXED -- some feasible but no net improvement. "
              "z3 lever marginal or shape constraints dominate.")

    # Save JSON
    out = os.path.join(THIS, "z3_realize_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"\n  Results saved: {out}")
    print("=" * 130)


if __name__ == "__main__":
    main()
