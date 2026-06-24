"""Unified crane-aware GREEDY CONSTRUCTIVE solver (uconstruct).

A deliberate architectural alternative to the CP-SAT-assignment-first +
realize-cuts pipeline (`rebuild.py`).  That pipeline decides the bay map first
(z1-blind, minimising z2+z3) and only then decodes timing; when a congested
preferred bay forces tardiness it evicts blocks to other bays, inflating z3.

`uconstruct` instead decides (bay, position, entry-time) JOINTLY, one block at a
time, in criticality order, crane-feasible BY CONSTRUCTION.  Reconstructed from
the SSP literature (He 2024 / DAS-CURVE / Shang & Gu): each block is placed into
the bay that minimises a marginal objective cost (w1*tardiness + w2*ΔZ2 +
w3*preference-deviation), at its earliest crane-safe window in that bay -- the
same fixed-time decode the floor uses (`fastfloor._fixed_time_decode`'s single
block step), never hand-rolling the j>=k crane geometry.

The result is then handed to the per-bay timing ORACLE
(`myalgorithm._cpsat_bay_timing_verified`) which re-times entries on the fixed
layout to drive z1 to its crane-induced minimum (z2/z3 provably unchanged), and
gated through `utils.check_feasibility`.

Self-contained: imports fastfloor / myalgorithm / utils / ogc_analysis only,
modifies none.

    python src/uconstruct.py    # self-test on prob_1,2,3,5,11 (train)
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fastfloor as FF                                            # noqa: E402
import myalgorithm as M                                           # noqa: E402
import utils                                                      # noqa: E402
from utils import Bay, Block                                      # noqa: E402

try:
    import packer as PK                                           # noqa: E402
except Exception:                                                 # pragma: no cover
    PK = None

try:
    import baypack_cp as BP                                       # noqa: E402
except Exception:                                                 # pragma: no cover
    BP = None


# ---------------------------------------------------------------------------
# Single-block crane-safe placement against an EXISTING placed list.
# Replicates _fixed_time_decode's per-block step (entry=R abut/grid, then walk
# placed exits, then forced empty window).  The j>=k crane geometry is REUSED
# from fastfloor (_ft_search_pos / _ft_interacting), never duplicated.
# ---------------------------------------------------------------------------

def _place_one(bay, bay_idx, b, blocks, placed, deadline):
    """Place block ``b`` against the EXISTING ``placed`` list in ``bay``.

    Mirrors `_fixed_time_decode`'s single-block placement: try the earliest
    window [R, R+P] (abut candidates + whole-bay grid), then walk entry over the
    placed exit times ascending (delayed), then a guaranteed empty window
    (forced, after every placed exit -> zero interactions).

    ``placed`` entries are the floor's dicts {a,e,n,layers,cbox,pbox}.  Returns
    (record, tardiness, placed_entry):
      * record       = {block_id, bay_id, x, y, orient_idx, entry_time, exit_time}
      * tardiness    = max(0, exit - due)
      * placed_entry = the {a,e,n,layers,cbox,pbox} dict to append to ``placed``
    Returns (None, math.inf, None) only if ``b`` cannot fit the bay at all.
    """
    blk = blocks[b]
    R = int(blk["release_time"]); P = int(blk["processing_time"])
    D = int(blk["due_date"])
    geo = FF._ft_geom(blk)
    # OGC_UC_NEST (default OFF): swap the BL-only `_ft_search_pos` for the
    # Extreme-Point + Largest-Contact-Area placer (denser co-present packing ->
    # fewer spills -> lower z3/objective).  Feasibility-superset of BL (it falls
    # back to `_ft_search_pos` when no dense spot verifies), so toggling it can
    # only change WHICH feasible spot is chosen, never feasibility itself.
    _search = (FF._ft_search_pos_lca
               if os.environ.get("OGC_UC_NEST", "0").strip().lower()
               in ("1", "true", "yes", "on")
               else FF._ft_search_pos)
    aB, eB = R, R + P
    pos = None
    if time.monotonic() < deadline - 0.2:
        pos = _search(b, blk, geo, bay, aB, eB,
                      FF._ft_interacting(placed, aB, eB), deadline, grid=True)
        if pos is None:
            for t in sorted({A["e"] for A in placed if A["e"] > R}):
                if time.monotonic() >= deadline - 0.2:
                    break
                aB, eB = t, t + P
                pos = _search(b, blk, geo, bay, aB, eB,
                              FF._ft_interacting(placed, aB, eB), deadline)
                if pos is not None:
                    break
    if pos is None:
        # forced empty window: after every placed exit -> zero interactions.
        aB = max([R] + [A["e"] for A in placed])
        eB = aB + P
        pos = _search(b, blk, geo, bay, aB, eB, [], deadline, grid=True)
        if pos is None:
            return None, math.inf, None                  # cannot fit the bay
    dx, dy, oi, wlayers, wcbox = pos
    pb = geo[oi][2]
    entry = {
        "a": aB, "e": eB, "n": len(wlayers),
        "layers": wlayers, "cbox": wcbox,
        "pbox": (pb[0] + dx, pb[1] + dy, pb[2] + dx, pb[3] + dy),
    }
    rec = {"block_id": b, "bay_id": bay_idx, "x": int(dx), "y": int(dy),
           "orient_idx": int(oi), "entry_time": int(aB), "exit_time": int(eB)}
    return rec, max(0.0, eB - D), entry


# ---------------------------------------------------------------------------
# z2 marginal: closed-form on the bay->load map (independent of x/y/timing).
# z2 (internal proxy, mirrors _objective) = max(u*load) - min(u*load).
# ---------------------------------------------------------------------------

def _is_feasible(prob_info, sol):
    """True iff the official checker accepts ``sol`` (key is ``feasible``)."""
    try:
        chk = utils.check_feasibility(prob_info, sol)
    except Exception:
        return False
    if isinstance(chk, dict):
        return bool(chk.get("feasible", chk.get("is_feasible", False)))
    return bool(chk)


# ---------------------------------------------------------------------------
# z2 marginal: closed-form on the bay->load map (independent of x/y/timing).
# z2 (internal proxy, mirrors _objective) = max(u*load) - min(u*load).
# ---------------------------------------------------------------------------

def _z2_imbalance(load, bay_u):
    nb = len(bay_u)
    if nb < 2:
        return 0.0
    wl = [bay_u[j] * load[j] for j in range(nb)]
    return max(wl) - min(wl)


# ---------------------------------------------------------------------------
# Criticality orderings.
# ---------------------------------------------------------------------------

def _order_slack(ids, blocks):
    """Tightest slack first; tie-break big (min-bbox-area) first."""
    return sorted(ids, key=lambda b: (
        int(blocks[b]["due_date"]) - int(blocks[b]["release_time"])
        - int(blocks[b]["processing_time"]),
        -FF._min_bbox_area(blocks[b])))


def _order_edd(ids, blocks):
    """Earliest due date; tie-break earliest release."""
    return sorted(ids, key=lambda b: (int(blocks[b]["due_date"]),
                                      int(blocks[b]["release_time"])))


# ---------------------------------------------------------------------------
# Core constructive pass over one block order.
# ---------------------------------------------------------------------------

def _construct(prob_info, blocks, bays, bay_u, feas, order, deadline,
               bay_target=None):
    """One joint constructive pass: for each block in ``order``, pick the bay
    that minimises marginal objective cost and commit its earliest crane-safe
    placement there.  Returns (results_dict, flat) or (None, None) if any block
    cannot be placed in any feasible bay before the deadline.

    results_dict = {bay_idx: {block_id: record}}."""
    w = prob_info.get("weights", {})
    w1 = float(w.get("w1", 1.0)); w2 = float(w.get("w2", 1.0))
    w3 = float(w.get("w3", 1.0))
    # z2 is small (w2<<w3) AND the greedy per-block ΔZ2 is misleading (early
    # loads are uneven, so "balancing" pushes blocks off preferred bays and
    # inflates z3 -- prob_1 z3 452 vs achievable 2).  Default: ignore z2 in the
    # placement decision (honour preferred bay unless tardiness forces a move);
    # z2 is handled, if at all, by a cheap global rebalance pass.
    w2 *= float(os.environ.get("OGC_UC_W2_MULT", "1.0"))
    nb = len(bays)

    placed = [[] for _ in range(nb)]          # floor placed-list per bay
    load = [0.0] * nb
    results = {j: {} for j in range(nb)}

    for b in order:
        if time.monotonic() >= deadline - 0.3:
            return None, None
        blk = blocks[b]
        wkl = float(blk["workload"])
        prefs = blk["bay_preferences"]
        max_pref = max(prefs)
        cur_imb = _z2_imbalance(load, bay_u)

        # CP-SAT bay-target guidance: try the globally-optimal (z2+z3) bay first;
        # if it realises crane-safe with ZERO tardiness, commit there -- inheriting
        # CP-SAT's global assignment.  Only fall through to the marginal-cost spill
        # search when the target bay is over-subscribed (tard>0).
        if bay_target is not None:
            jt = bay_target[b]
            if 0 <= jt < nb and (not feas[b] or jt in feas[b]):
                rec, tard, entry = _place_one(bays[jt], jt, b, blocks,
                                              placed[jt], deadline)
                if rec is not None and tard <= 1e-9:
                    results[jt][b] = rec
                    placed[jt].append(entry)
                    load[jt] += wkl
                    continue

        cands = feas[b] if feas[b] else list(range(nb))
        best = None          # (cost, tard, z3, j, rec, entry)
        for j in cands:
            if time.monotonic() >= deadline - 0.3:
                break
            rec, tard, entry = _place_one(bays[j], j, b, blocks,
                                          placed[j], deadline)
            if rec is None:
                continue
            load[j] += wkl
            d_imb = _z2_imbalance(load, bay_u) - cur_imb
            load[j] -= wkl
            z3j = max_pref - prefs[j]
            cost = w1 * tard + w2 * d_imb + w3 * z3j
            key = (cost, tard, z3j)
            if best is None or key < (best[0], best[1], best[2]):
                best = (cost, tard, z3j, j, rec, entry)
        if best is None:
            return None, None                 # block fits no feasible bay
        _, _, _, j, rec, entry = best
        results[j][b] = rec
        placed[j].append(entry)
        load[j] += wkl

    flat = [a for by in results.values() for a in by.values()]
    return results, flat


# ---------------------------------------------------------------------------
# CP-PACK constructive: dense per-bay EXACT packing (baypack_cp) of the CP-SAT
# z3+z2-optimal bay map, then minimal-z3 spill of the genuine overflow.
#
# `_construct` commits each block to its target bay only if a single greedy
# fixed-time placement realises z1=0 there, else SPILLS immediately (z3 cost).
# The greedy placement leaves gaps -> bays go tardy -> more spilling -> higher
# z3.  `_construct_cppack` instead packs each target bay's FULL block set DENSELY
# (baypack_cp.pack_bay_cp -- exact bbox pack minimising bay tardiness, crane-safe
# by the box-contains-polygon property), so MORE blocks fit at z1=0 and fewer
# need to spill.  Only the bays still tardy after dense packing spill, one cheap
# block at a time, re-packing both affected bays.
# ---------------------------------------------------------------------------

def _pack_bay(prob_info, bay, bay_idx, members, blocks, deadline, cp_budget,
              max_blk):
    """Pack ``members`` into ``bay`` densely.  Prefer the exact CP-SAT packer
    (baypack_cp.pack_bay_cp); fall back to the greedy `_decode_bay` when the
    packer is unavailable, the bay is too big (> ``max_blk``), or CP-SAT finds
    no solution in budget.  Returns (records_dict | None, tardiness)."""
    if not members:
        return {}, 0.0
    use_cp = (BP is not None and len(members) <= max_blk and cp_budget > 0.5
              and time.monotonic() < deadline - 1.0)
    if use_cp:
        cp_dl = min(deadline, time.monotonic() + cp_budget + 1.0)
        try:
            recs, tard = BP.pack_bay_cp(prob_info, bay, bay_idx, list(members),
                                        cp_dl, time_budget=cp_budget)
        except Exception:
            recs = None
        if recs is not None and set(recs.keys()) == set(members):
            return recs, tard
    # Greedy fallback (the same per-block crane-safe step `_construct` uses).
    return _decode_bay(bay, bay_idx, members, blocks, deadline)


def _construct_cppack(prob_info, blocks, bays, bay_u, feas, deadline,
                      bay_target, cp_budget_per_bay, max_blk):
    """Dense-pack-then-spill constructive.

    1. Assign EVERY block to ``bay_target[b]`` (CP-SAT z3+z2-optimal); when that
       is missing/infeasible fall back to the most-preferred feasible bay.  Build
       full per-bay block sets (NO per-block spilling).
    2. Pack each bay's set densely via `_pack_bay` (exact CP-SAT or greedy
       fallback).
    3. For bays still TARDY, spill the minimal-z3 overflow: repeatedly move the
       tardy bay's cheapest-z3-to-evict block to its best alternative feasible
       bay, re-pack BOTH affected bays, until the bay is z1=0 or no improving
       spill remains.

    Returns ``results_dict`` {bay_idx: {block_id: record}} (z1 may still be >0 if
    unspillable; the downstream timing oracle + checker gate handle that), or
    None if construction fails outright."""
    nb = len(bays)

    # --- Step 1: full per-bay block sets from the CP-SAT bay map. -----------
    members = {j: [] for j in range(nb)}
    for b in range(len(blocks)):
        jt = bay_target[b] if (bay_target is not None and b < len(bay_target)) else -1
        cands = feas[b] if feas[b] else list(range(nb))
        if not (0 <= jt < nb and (not feas[b] or jt in feas[b])):
            # No (valid) CP-SAT target: most-preferred feasible bay.
            prefs = blocks[b]["bay_preferences"]
            jt = max(cands, key=lambda j: prefs[j])
        members[jt].append(b)

    # --- Step 2: dense pack each bay. --------------------------------------
    results = {j: {} for j in range(nb)}
    for j in range(nb):
        if not members[j]:
            continue
        if time.monotonic() >= deadline - 0.5:
            return None
        recs, _ = _pack_bay(prob_info, bays[j], j, members[j], blocks,
                            deadline, cp_budget_per_bay, max_blk)
        if recs is None:
            return None                       # a bay's set cannot be packed
        results[j] = recs

    def bay_tard(by):
        return sum(max(0.0, int(a["exit_time"]) - int(blocks[b]["due_date"]))
                   for b, a in by.items())

    # --- Step 3: minimal-z3 spill of the genuine overflow. -----------------
    # Only AFTER dense packing.  The CP-SAT bay map is z1-BLIND, so a preference
    # magnet bay can be over-subscribed (more blocks than fit at z1=0 even when
    # packed densely).  Relieve it by moving the cheapest-z3 block to its best
    # alternative feasible bay.
    #
    # Each trial is evaluated with the FAST greedy `_decode_bay` (CP-SAT re-pack
    # per trial would be O(n) seconds and starve the deadline -- the diagnosis of
    # the first cut).  We track each bay's working member set and its greedy
    # tardiness; a move is accepted iff the source bay's greedy tardiness strictly
    # drops AND the combined source+target greedy tardiness does not rise.  After
    # the spill loop settles, the CHANGED bays are re-packed once with CP-SAT
    # (dense) so the final layout keeps the exact-packer quality.
    spill_budget = max(0.5, cp_budget_per_bay * 0.6)
    max_spills = int(os.environ.get("OGC_UC_CPPACK_MAXSPILL", "60"))

    # Working member sets + greedy tardiness per bay (the spill search basis).
    cur_members = {j: list(results[j].keys()) for j in range(nb)}

    def greedy_tard(j, mem):
        if not mem:
            return 0.0
        recs, t = _decode_bay(bays[j], j, mem, blocks, deadline)
        return t if recs is not None else math.inf

    g_tard = {j: greedy_tard(j, cur_members[j]) for j in range(nb)}
    changed_bays = set()
    spills = 0
    progress = True
    while progress and spills < max_spills:
        progress = False
        if time.monotonic() >= deadline - 0.5:
            break
        tardy = sorted((j for j in range(nb) if g_tard[j] > 1e-9),
                       key=lambda j: -g_tard[j])
        for jf in tardy:
            if time.monotonic() >= deadline - 0.5:
                break
            src_tard = g_tard[jf]
            # Evict candidates: blocks with a strictly different feasible bay,
            # ordered by z3 cost to evict ascending (cheapest preference loss).
            evictees = []
            for b in cur_members[jf]:
                cands = feas[b] if feas[b] else list(range(nb))
                alts = [jt for jt in cands if jt != jf]
                if not alts:
                    continue
                prefs = blocks[b]["bay_preferences"]
                jt_best = max(alts, key=lambda jt: prefs[jt])
                z3_cost = prefs[jf] - prefs[jt_best]   # >=0: preference lost
                evictees.append((z3_cost, b, jt_best))
            evictees.sort(key=lambda e: (e[0], e[1]))
            moved = False
            for z3_cost, b, jt in evictees:
                if time.monotonic() >= deadline - 0.5:
                    break
                new_src = [x for x in cur_members[jf] if x != b]
                new_tgt = cur_members[jt] + [b]
                tard_f = greedy_tard(jf, new_src)
                if not (tard_f < src_tard - 1e-9):
                    continue
                tard_t = greedy_tard(jt, new_tgt)
                old_combo = src_tard + g_tard[jt]
                new_combo = tard_f + tard_t
                if new_combo <= old_combo + 1e-9:
                    cur_members[jf] = new_src
                    cur_members[jt] = new_tgt
                    g_tard[jf] = tard_f
                    g_tard[jt] = tard_t
                    changed_bays.add(jf)
                    changed_bays.add(jt)
                    spills += 1
                    moved = True
                    progress = True
                    break
            if moved:
                break                          # recompute tardy set fresh

    # Re-pack the CHANGED bays densely with CP-SAT (the spill search ran on the
    # cheap greedy decode; this restores exact-packer density on the new sets).
    for j in changed_bays:
        if time.monotonic() >= deadline - 0.5:
            break
        recs, _ = _pack_bay(prob_info, bays[j], j, cur_members[j], blocks,
                            deadline, cp_budget_per_bay, max_blk)
        if recs is not None and set(recs.keys()) == set(cur_members[j]):
            results[j] = recs
        else:
            # CP-SAT failed on the new set: fall back to greedy decode.
            recs, _ = _decode_bay(bays[j], j, cur_members[j], blocks, deadline)
            if recs is None:
                return None
            results[j] = recs

    # --- Step 4: cheap reconcile of residual tardiness on the EXACT layout. --
    # The spill search optimised the greedy-decode proxy; the final exact pack
    # can leave a tiny 1-2 unit crane-wash residual the proxy did not see.  One
    # cheap drain pass on the TRUE per-bay tardiness: for each genuinely tardy
    # bay, find the cheapest-z3 block whose removal makes the GREEDY source decode
    # strictly better and whose best-alternative greedy decode stays 0, then
    # CP-SAT re-pack ONLY the two accepted bays (trials use the fast greedy
    # proxy, never CP-SAT -- the same wall-discipline as step 3).  A genuine
    # structural wash (block tardy by 1 in every feasible bay) is left as-is.
    extra = int(os.environ.get("OGC_UC_CPPACK_DRAIN", "8"))
    drained = 0
    progress = True
    while progress and drained < extra:
        progress = False
        if time.monotonic() >= deadline - 1.0:
            break
        tardy = sorted((j for j in range(nb) if bay_tard(results[j]) > 1e-9),
                       key=lambda j: -bay_tard(results[j]))
        for jf in tardy:
            if time.monotonic() >= deadline - 1.0:
                break
            src_tard = bay_tard(results[jf])
            mem_f = list(results[jf].keys())
            evictees = []
            for b in mem_f:
                cands = feas[b] if feas[b] else list(range(nb))
                alts = [jt for jt in cands if jt != jf]
                if not alts:
                    continue
                prefs = blocks[b]["bay_preferences"]
                jt_best = max(alts, key=lambda jt: prefs[jt])
                z3_cost = prefs[jf] - prefs[jt_best]
                evictees.append((z3_cost, b, jt_best))
            evictees.sort(key=lambda e: (e[0], e[1]))
            moved = False
            for z3_cost, b, jt in evictees:
                if time.monotonic() >= deadline - 1.0:
                    break
                mem_t = list(results[jt].keys())
                new_src = [x for x in mem_f if x != b]
                new_tgt = mem_t + [b]
                # Cheap greedy pre-screen (no CP-SAT in the trial loop).
                gf = greedy_tard(jf, new_src)
                if not (gf < greedy_tard(jf, mem_f) - 1e-9):
                    continue
                gt = greedy_tard(jt, new_tgt)
                if gt > greedy_tard(jt, mem_t) + 1e-9:
                    continue
                # Accepted by proxy -> CP-SAT re-pack the two bays once.
                recs_f, tard_f = _pack_bay(prob_info, bays[jf], jf, new_src,
                                           blocks, deadline, spill_budget,
                                           max_blk)
                if recs_f is None or not (tard_f < src_tard - 1e-9):
                    continue
                recs_t, tard_t = _pack_bay(prob_info, bays[jt], jt, new_tgt,
                                           blocks, deadline, spill_budget,
                                           max_blk)
                if recs_t is None:
                    continue
                old_combo = src_tard + bay_tard(results[jt])
                if tard_f + tard_t <= old_combo + 1e-9:
                    results[jf] = recs_f
                    results[jt] = recs_t
                    drained += 1
                    moved = True
                    progress = True
                    break
            if moved:
                break
    return results


# ---------------------------------------------------------------------------
# z3 (preference) improvement local search.
#
# The official weights are w2 (≈5) << w3 (≈133): a move that raises z2 a little
# while lowering z3 is net objective-NEGATIVE.  The competitor exploits exactly
# this (accept high z2 to keep blocks in preferred bays -> low z3); the legacy
# Front-B is too z2-conservative and gets stuck (prob_11 z3=338 vs competitor
# 167).  This pass AGGRESSIVELY trades z2 up for z3 down: move z3-offender blocks
# toward more-preferred bays, re-decode the two affected bays crane-safe, and
# accept iff z1 stays 0 globally AND the weighted objective strictly improves.
#
# Re-decode = replay `_place_one` over a bay's member set in EDD order (due asc).
# That mirrors the constructive's per-block crane-safe step exactly, so a bay's
# decode here is consistent with how `_construct` built it.
# ---------------------------------------------------------------------------

def _decode_bay(bay, bay_idx, members, blocks, deadline):
    """Replay `_place_one` over ``members`` (a block-id iterable) in EDD order
    against a FRESH placed list for bay ``bay_idx``.  Returns
    (records_dict, total_tardiness) or (None, math.inf) if any block fails to
    fit / the deadline is hit.  records_dict = {block_id: record}."""
    order = sorted(members, key=lambda b: (int(blocks[b]["due_date"]),
                                           int(blocks[b]["release_time"]),
                                           int(blocks[b]["processing_time"])))
    placed = []
    recs = {}
    tard = 0.0
    for b in order:
        if time.monotonic() >= deadline - 0.3:
            return None, math.inf
        rec, t, entry = _place_one(bay, bay_idx, b, blocks, placed, deadline)
        if rec is None:
            return None, math.inf
        placed.append(entry)
        recs[b] = rec
        tard += t
    return recs, tard


def _sol_z1(prob_info, sol):
    """Total tardiness (z1) of a solution dict: sum max(0, exit - due)."""
    blocks = prob_info["blocks"]
    exit_t = {}
    for t_str, ops in sol.get("operations", {}).items():
        for op in ops:
            if op.get("type") != "ENTRY":          # EXIT carries the exit time
                exit_t[op["block_id"]] = int(t_str)
    z1 = 0.0
    for bid, et in exit_t.items():
        z1 += max(0.0, et - int(blocks[bid]["due_date"]))
    return z1


def _bay_z1_achievable(prob_info, bays, bay_idx, recs, deadline):
    """True iff bay ``bay_idx`` with fixed layout ``recs`` ({bid: record}) can
    be re-timed to ZERO tardiness by the per-bay timing oracle.

    The constructive's raw per-block records are often slightly tardy (the
    global timing oracle fixes them afterward), so a fresh re-decode's
    tardiness is NOT the right z1 gate -- the oracle's achievable tardiness is.
    Since intrinsicLB=0 on all train instances, "achievable z1=0" == "the
    oracle can re-time this fixed layout to no tardiness".  Calling the oracle
    on a single-bay sub-results mirrors how `solve_unified` re-times the whole
    candidate, so the per-move gate agrees with the final objective gate."""
    blocks = prob_info["blocks"]
    raw = sum(max(0.0, int(a["exit_time"]) - int(blocks[b]["due_date"]))
              for b, a in recs.items())
    if raw <= 1e-9:
        return True
    sub = {bay_idx: {b: dict(a) for b, a in recs.items()}}
    try:
        imp = M._cpsat_bay_timing_verified(prob_info, bays, sub,
                                           deadline=deadline)
    except Exception:
        imp = None
    if imp is None:
        # Oracle skipped/failed -> trust raw (conservative: raw>0 => reject).
        return raw <= 1e-9
    return _sol_z1(prob_info, imp) <= 1e-9


def _z3_improve(prob_info, blocks, bays, bay_u, results, deadline,
                time_budget):
    """z3-down / z2-up local search on a z1=0 ``results`` map.

    For each block currently NOT in a top-preference bay (z3>0), in descending
    z3-contribution order, try moving it to each strictly-more-preferred bay.
    Re-decode the source and target bays crane-safe; accept the move iff both
    bays can be re-timed to z1=0 by the per-bay timing oracle (z1 stays 0
    globally) AND ``w3*Δz3 + w2*Δz2 < -eps`` (net objective improves).  Pure
    descent over repeated passes until no improving move or the budget runs out.

    Returns an updated results map (deep-copied, never the input object) on
    success, or ``None`` if nothing improved / anything went wrong.  Never
    returns a z1>0 or broken state."""
    nb = len(bays)
    if nb < 2:
        return None
    w = prob_info.get("weights", {})
    w2 = float(w.get("w2", 1.0)); w3 = float(w.get("w3", 1.0))
    eps = 1e-6
    _swaps_on = os.environ.get("OGC_UC_Z3SWAP", "1").strip().lower() in (
        "1", "true", "yes", "on")
    _swap_k = int(os.environ.get("OGC_UC_Z3SWAP_K", "8"))
    t_end = min(deadline, time.monotonic() + max(0.0, float(time_budget)))
    if time.monotonic() >= t_end - 0.3:
        return None

    # Working state: deep copy of results + bay->load map + block->bay index.
    res = {j: {b: dict(a) for b, a in by.items()} for j, by in results.items()}
    for j in range(nb):
        res.setdefault(j, {})
    load = [0.0] * nb
    cur_bay = {}
    for j in range(nb):
        for b, a in res[j].items():
            load[j] += float(blocks[b]["workload"])
            cur_bay[b] = j

    def imbalance(ld):
        return _z2_imbalance(ld, bay_u)

    improved_any = False
    pass_count = 0
    max_passes = int(os.environ.get("OGC_UC_Z3PASSES", "6"))
    while pass_count < max_passes:
        pass_count += 1
        if time.monotonic() >= t_end - 0.3:
            break
        # Candidate offenders: blocks with z3>0, biggest contribution first.
        cands = []
        for b, jf in cur_bay.items():
            prefs = blocks[b]["bay_preferences"]
            z3c = max(prefs) - prefs[jf]
            if z3c > 0:
                cands.append((z3c, b))
        if not cands:
            break
        cands.sort(reverse=True)

        moved_this_pass = False
        for z3c, b in cands:
            if time.monotonic() >= t_end - 0.3:
                break
            jf = cur_bay[b]
            prefs = blocks[b]["bay_preferences"]
            wkl = float(blocks[b]["workload"])
            # More-preferred bays, descending preference (best target first).
            targets = sorted(
                (jt for jt in range(nb)
                 if jt != jf and prefs[jt] > prefs[jf]),
                key=lambda jt: -prefs[jt])
            if not targets:
                continue
            cur_imb = imbalance(load)
            src_members = [x for x in res[jf].keys() if x != b]
            best_move = None  # (gain, jt, recs_f, recs_t)
            for jt in targets:
                if time.monotonic() >= t_end - 0.3:
                    break
                d_z3 = prefs[jf] - prefs[jt]          # < 0 (jt more preferred)
                new_load = list(load)
                new_load[jf] -= wkl
                new_load[jt] += wkl
                d_z2 = imbalance(new_load) - cur_imb
                gain = w3 * d_z3 + w2 * d_z2           # < 0 means improvement
                # Cheap gain gate first; only re-decode + oracle-check the layout
                # when the move could improve (and beat the running best).
                if not (gain < -eps and
                        (best_move is None or gain < best_move[0])):
                    continue
                # Re-decode source (lose b) and target (gain b) crane-safe.  The
                # raw re-decode timing may be tardy (the oracle fixes it later),
                # so the z1 gate is "oracle can re-time this layout to 0", which
                # matches solve_unified's final re-time + objective gate.
                recs_t, _ = _decode_bay(bays[jt], jt, list(res[jt].keys()) + [b],
                                        blocks, t_end)
                if recs_t is None:
                    continue
                if not _bay_z1_achievable(prob_info, bays, jt, recs_t, t_end):
                    continue
                recs_f, _ = _decode_bay(bays[jf], jf, src_members, blocks, t_end)
                if recs_f is None:
                    continue
                if not _bay_z1_achievable(prob_info, bays, jf, recs_f, t_end):
                    continue
                best_move = (gain, jt, recs_f, recs_t)
            # SWAP fallback: when no plain relocation lands (the preferred bays
            # are saturated -- prob_3/prob_6), try EXCHANGING b with a block c in
            # a more-preferred bay.  Freeing c's slot makes room for b at z1=0;
            # net z3 change = (prefs_b[jf]-prefs_b[jt]) + (prefs_c[jt]-prefs_c[jf]).
            # Pick c by similar workload (keeps both bays packable) + low z3 cost
            # to evict.  Only attempted if the plain relocation found nothing.
            if best_move is None and _swaps_on:
                for jt in targets:
                    if time.monotonic() >= t_end - 0.3:
                        break
                    d_z3_b = prefs[jf] - prefs[jt]     # < 0
                    # Candidate partners in jt: prefer those cheap to evict to jf
                    # (high prefs_c[jf]) and close in workload to b.
                    parts = sorted(
                        res[jt].keys(),
                        key=lambda c: (
                            -(blocks[c]["bay_preferences"][jf]
                              - blocks[c]["bay_preferences"][jt]),
                            abs(float(blocks[c]["workload"]) - wkl)))
                    for c in parts[:_swap_k]:
                        if time.monotonic() >= t_end - 0.3:
                            break
                        cp = blocks[c]["bay_preferences"]
                        cwkl = float(blocks[c]["workload"])
                        d_z3 = d_z3_b + (cp[jt] - cp[jf])
                        if not d_z3 < 0:              # swap must lower z3
                            continue
                        new_load = list(load)
                        new_load[jf] += cwkl - wkl
                        new_load[jt] += wkl - cwkl
                        d_z2 = imbalance(new_load) - cur_imb
                        gain = w3 * d_z3 + w2 * d_z2
                        if not gain < -eps:
                            continue
                        # Re-decode both bays with b<->c swapped, oracle-gated.
                        tgt_members = [x for x in res[jt].keys() if x != c] + [b]
                        recs_t, _ = _decode_bay(bays[jt], jt, tgt_members,
                                                blocks, t_end)
                        if recs_t is None or not _bay_z1_achievable(
                                prob_info, bays, jt, recs_t, t_end):
                            continue
                        src_members2 = src_members + [c]
                        recs_f, _ = _decode_bay(bays[jf], jf, src_members2,
                                                blocks, t_end)
                        if recs_f is None or not _bay_z1_achievable(
                                prob_info, bays, jf, recs_f, t_end):
                            continue
                        best_move = (gain, jt, recs_f, recs_t, c)
                        break
                    if best_move is not None:
                        break
            if best_move is not None:
                if len(best_move) == 5:               # swap move
                    _, jt, recs_f, recs_t, c = best_move
                    cwkl = float(blocks[c]["workload"])
                    res[jf] = recs_f
                    res[jt] = recs_t
                    load[jf] += cwkl - wkl
                    load[jt] += wkl - cwkl
                    cur_bay[b] = jt
                    cur_bay[c] = jf
                else:                                 # relocation move
                    _, jt, recs_f, recs_t = best_move
                    res[jf] = recs_f
                    res[jt] = recs_t
                    load[jf] -= wkl
                    load[jt] += wkl
                    cur_bay[b] = jt
                improved_any = True
                moved_this_pass = True
        if not moved_this_pass:
            break

    if not improved_any:
        return None
    return res


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def solve_unified(prob_info, timelimit, t_start, bays, bay_u, bay_target=None):
    """Unified crane-aware greedy constructive solve.

    Decides (bay, position, entry-time) jointly per block in criticality order,
    crane-feasible by construction; then improves z1 with the per-bay timing
    oracle and gates through the official feasibility checker.

    Returns a solution dict {"operations": ...} that PASSES
    ``utils.check_feasibility``, or None if no feasible construction was found
    within the wall budget.
    """
    blocks = prob_info["blocks"]
    deadline = t_start + 0.85 * float(timelimit)

    try:
        feas = M._feasible_bays(blocks, bays)
    except Exception:
        feas = [list(range(len(bays))) for _ in blocks]
    feas = [(f if f else list(range(len(bays)))) for f in feas]

    # CP-SAT bay-target: the global z2+z3-optimal assignment (z1-blind).  The
    # constructive realises it crane-safe at z1=0, spilling only the genuine
    # overflow -> inherits CP-SAT's low z2+z3 AND z1=0 by construction.  Computed
    # here if not supplied; None-safe (falls back to pure greedy marginal cost).
    _cpsat_on = os.environ.get("OGC_UC_CPSAT", "1").strip().lower() in ("1", "true", "yes", "on")
    if bay_target is None and _cpsat_on and len(bays) >= 2:
        try:
            fb = feas
            bay_target = M._cpsat_assignment(prob_info, bays, fb, bay_u,
                                             time_budget=min(20.0, 0.25 * timelimit))
        except Exception:
            bay_target = None

    ids = list(range(len(blocks)))
    orders = [_order_slack(ids, blocks), _order_edd(ids, blocks)]

    best_sol = None
    best_obj = math.inf
    best_results = None

    for order in orders:
        if time.monotonic() >= deadline - 0.5:
            break
        results, flat = _construct(prob_info, blocks, bays, bay_u, feas,
                                   order, deadline, bay_target=bay_target)
        if results is None or not flat:
            continue
        sol = {"operations": M._build_operations(flat)}
        # Improve z1 via the per-bay timing oracle (z2/z3 provably unchanged).
        try:
            imp = M._cpsat_bay_timing_verified(prob_info, bays, results,
                                               deadline=deadline)
        except Exception:
            imp = None
        if imp is not None:
            # The oracle already gates internally; prefer it if it scores lower.
            comp_imp = M._components_from_solution(prob_info, imp, bay_u)
            comp_sol = M._components_from_solution(prob_info, sol, bay_u)
            if (comp_imp is not None and
                    (comp_sol is None or comp_imp[0] <= comp_sol[0] + 1e-9)):
                sol = imp

        # Gate through the official checker before ranking.
        if not _is_feasible(prob_info, sol):
            continue
        comp = M._components_from_solution(prob_info, sol, bay_u)
        obj = comp[0] if comp is not None else math.inf
        if obj < best_obj:
            best_obj = obj
            best_sol = sol
            best_results = results

    # CP-PACK candidate: dense per-bay EXACT packing of the CP-SAT bay map +
    # minimal-z3 spill (only the genuine overflow).  Packs preferred bays denser
    # so fewer blocks spill to non-preferred bays -> lower z3.  Run as an
    # ADDITIONAL candidate alongside `_construct`; kept ONLY if it re-times +
    # gates feasible AND its objective beats the non-cppack construction (never
    # regress).  Default OFF (OGC_UC_CPPACK); deadline-bounded so no -1.
    _cppack_on = os.environ.get("OGC_UC_CPPACK", "0").strip().lower() in (
        "1", "true", "yes", "on")
    if (_cppack_on and BP is not None and len(bays) >= 1
            and time.monotonic() < deadline - 2.0):
        n_bays = max(1, len(bays))
        cp_budget = min(
            float(os.environ.get("OGC_UC_CPPACK_BUDGET", "8")),
            max(0.5, (deadline - time.monotonic()) / n_bays))
        max_blk = int(os.environ.get("OGC_UC_CPPACK_MAXBLK", "70"))
        try:
            cp_results = _construct_cppack(prob_info, blocks, bays, bay_u, feas,
                                           deadline, bay_target, cp_budget,
                                           max_blk)
        except Exception:
            cp_results = None
        if cp_results is not None:
            flat_cp = [a for by in cp_results.values() for a in by.values()]
            if flat_cp:
                cp_sol = {"operations": M._build_operations(flat_cp)}
                # Re-time z1 via the per-bay oracle (z2/z3 invariant).
                try:
                    imp_cp = M._cpsat_bay_timing_verified(
                        prob_info, bays, cp_results, deadline=deadline)
                except Exception:
                    imp_cp = None
                if imp_cp is not None:
                    ci = M._components_from_solution(prob_info, imp_cp, bay_u)
                    cc = M._components_from_solution(prob_info, cp_sol, bay_u)
                    if ci is not None and (cc is None or ci[0] <= cc[0] + 1e-9):
                        cp_sol = imp_cp
                if _is_feasible(prob_info, cp_sol):
                    comp_cp = M._components_from_solution(prob_info, cp_sol,
                                                          bay_u)
                    obj_cp = comp_cp[0] if comp_cp is not None else math.inf
                    if obj_cp < best_obj - 1e-9:
                        best_obj = obj_cp
                        best_sol = cp_sol
                        best_results = cp_results

    if best_sol is None:
        return None

    # z3-descent: trade z2 up for z3 down (w2<<w3) by moving offender blocks
    # toward preferred bays.  Operates on the z1=0 layout, re-times via the
    # oracle, gates through the official checker, and is kept ONLY if the full
    # solution stays feasible AND total objective strictly improves.
    # Default OFF: the z3-descent lowers obj on LOSS instances but flips no wins
    # (competition is per-instance rank, not total obj), and it adds CP-SAT
    # runtime that risks starving the unified construction inside the augment's
    # 45s cap.  Kept gated for experiments; OFF preserves the validated 10/20.
    _z3desc_on = os.environ.get("OGC_UC_Z3DESCENT", "0").strip().lower() in (
        "1", "true", "yes", "on")
    if (_z3desc_on and best_results is not None
            and time.monotonic() < deadline - 1.0):
        budget = min(0.4 * float(timelimit),
                     max(0.0, deadline - time.monotonic() - 1.0))
        z3res = _z3_improve(prob_info, blocks, bays, bay_u, best_results,
                            deadline, budget)
        if z3res is not None:
            flat2 = [a for by in z3res.values() for a in by.values()]
            cand = {"operations": M._build_operations(flat2)}
            # Re-time z1 on the new layout (z2/z3 invariant), prefer if lower.
            try:
                imp2 = M._cpsat_bay_timing_verified(prob_info, bays, z3res,
                                                    deadline=deadline)
            except Exception:
                imp2 = None
            if imp2 is not None:
                ci = M._components_from_solution(prob_info, imp2, bay_u)
                cc = M._components_from_solution(prob_info, cand, bay_u)
                if ci is not None and (cc is None or ci[0] <= cc[0] + 1e-9):
                    cand = imp2
            if _is_feasible(prob_info, cand):
                comp2 = M._components_from_solution(prob_info, cand, bay_u)
                if comp2 is not None and comp2[0] < best_obj - 1e-9:
                    best_obj = comp2[0]
                    best_sol = cand
                    best_results = z3res

    # Optional jostle: re-pack the most-tardy bay (remove a few blocks, re-insert
    # in EDD order) if budget remains.  Kept simple + reverts unless the whole
    # solution's objective strictly improves.  Skipped on any risk.
    if time.monotonic() < deadline - 1.0 and best_results is not None:
        jostled = _jostle(prob_info, blocks, bays, bay_u, best_results,
                          best_obj, deadline)
        if jostled is not None:
            best_sol = jostled

    return best_sol


# ---------------------------------------------------------------------------
# Jostle improvement (single-bay re-pack).  Conservative: only the bay with the
# most tardiness, only its own block subset re-inserted in EDD order, oracle
# re-timed, and accepted iff the full solution's objective strictly improves.
# ---------------------------------------------------------------------------

def _jostle(prob_info, blocks, bays, bay_u, results, base_obj, deadline):
    def bay_tard(by):
        return sum(max(0.0, a["exit_time"] - int(blocks[b]["due_date"]))
                   for b, a in by.items())

    # Re-pack EVERY tardy bay (worst first) via packer.pack_bay's repositioning
    # local search -- this is the move the per-bay timing oracle cannot make
    # (it re-positions placed blocks, not just re-times them).  z2/z3 are bay-map
    # invariant, so re-packing within a bay can only change z1.  Each bay re-pack
    # is never worse than its current decode (pack_bay retains the seed floor),
    # so we accept the rebuilt layout whenever the full solution stays feasible
    # and its objective does not regress.
    if PK is None:
        return None
    tardy_bays = sorted((j for j, by in results.items()
                         if bay_tard(by) > 1e-9),
                        key=lambda j: -bay_tard(results[j]))
    if not tardy_bays:
        return None

    new_results = {j: {k: dict(v) for k, v in by.items()}
                   for j, by in results.items()}
    changed = False
    for j in tardy_bays:
        if time.monotonic() >= deadline - 1.0:
            break
        mem = list(new_results[j].keys())
        if len(mem) < 2:
            continue
        budget = max(2.0, min(20.0, (deadline - time.monotonic()) /
                              max(1, len(tardy_bays))))
        try:
            packed, _ = PK.pack_bay(bays[j], j, mem, blocks,
                                    deadline=time.monotonic() + budget,
                                    time_budget=budget)
        except Exception:
            packed = None
        if packed is None or set(packed.keys()) != set(mem):
            continue
        for b in mem:
            packed[b]["bay_id"] = j           # pack_bay's reinsert path sets None
        new_results[j] = packed
        changed = True
    if not changed:
        return None

    flat = [a for by in new_results.values() for a in by.values()]
    sol = {"operations": M._build_operations(flat)}
    try:
        imp = M._cpsat_bay_timing_verified(prob_info, bays, new_results,
                                           deadline=deadline)
    except Exception:
        imp = None
    if imp is not None:
        ic = M._components_from_solution(prob_info, imp, bay_u)
        sc = M._components_from_solution(prob_info, sol, bay_u)
        if ic is not None and (sc is None or ic[0] <= sc[0] + 1e-9):
            sol = imp
    if not _is_feasible(prob_info, sol):
        return None
    comp = M._components_from_solution(prob_info, sol, bay_u)
    if comp is None or comp[0] >= base_obj - 1e-9:
        return None
    return sol


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _make_bays_and_u(prob):
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    areas = [prob["bays"][j]["width"] * prob["bays"][j]["height"]
             for j in range(nb)]
    avg = sum(areas) / nb
    bay_u = [avg / a for a in areas]
    return bays, bay_u


def _eval_inst(prob, bays, bay_u, OA, timelimit=60):
    """Run solve_unified once and return (feas, obj, z1, z2, z3, wall)."""
    t0 = time.monotonic()
    sol = solve_unified(prob, timelimit, time.monotonic(), bays, bay_u)
    wall = time.monotonic() - t0
    if sol is None:
        return False, None, None, None, None, wall
    feas = False; obj = z1 = z2 = z3 = None
    if OA is not None:
        try:
            feas, obj, z1, z2, z3 = OA.obj_tuple(prob, sol)
        except Exception:
            feas = False
    if not feas:
        comp = M._components_from_solution(prob, sol, bay_u)
        if comp is not None:
            obj, z1, z2, z3 = comp
            feas = _is_feasible(prob, sol)
    return feas, obj, z1, z2, z3, wall


def _selftest():
    import json
    try:
        import ogc_analysis as OA
    except Exception:
        OA = None

    # Close losses (prob_11/17), prob_15 (existing win, must not regress), and
    # prob_3/prob_6.  Toggle OGC_UC_CPPACK to compare WITH vs WITHOUT the dense
    # per-bay exact packer.  Realistic timelimit so the CP-SAT packer has budget.
    TL = int(os.environ.get("OGC_UC_SELFTEST_TL", "200"))
    competitor = {"prob_3": 50642, "prob_6": 72400, "prob_11": 31899,
                  "prob_15": 48206, "prob_17": 62070}
    insts = ["prob_3", "prob_6", "prob_11", "prob_15", "prob_17"]

    print("=" * 114)
    print(f"uconstruct CP-PACK self-test (OGC_UC_CPPACK on/off, timelimit={TL}s)")
    print("=" * 114)
    print(f"{'inst':<9} {'mode':<5} {'obj':>10} {'z1':>6} {'z2':>8} {'z3':>8} "
          f"{'wall':>6}  {'compet':>8} {'vs':>8}  {'feas':>5}  {'Δobj':>9} "
          f"{'Δz3':>8}  beats?")
    print("-" * 114)
    rows = {}
    for inst in insts:
        path = _ROOT / "instances" / "train" / f"{inst}.json"
        prob = json.load(open(path, encoding="utf-8"))

        # WITHOUT cppack (baseline _construct).
        os.environ["OGC_UC_CPPACK"] = "0"
        bays, bay_u = _make_bays_and_u(prob)
        off = _eval_inst(prob, bays, bay_u, OA, timelimit=TL)

        # WITH cppack (dense pack + spill candidate).
        os.environ["OGC_UC_CPPACK"] = "1"
        bays, bay_u = _make_bays_and_u(prob)
        on = _eval_inst(prob, bays, bay_u, OA, timelimit=TL)

        rows[inst] = (off, on)
        c = competitor.get(inst)
        for mode, r in (("OFF", off), ("ON", on)):
            feas, obj, z1, z2, z3, wall = r
            if obj is None:
                print(f"{inst:<9} {mode:<5} {'NONE (no feasible construction)':<40}"
                      f"  {wall:6.1f}")
                continue
            vs = "--" if c is None else f"{(obj - c) / c * 100:+.0f}%"
            z3s = f"{z3:.0f}" if z3 is not None else "--"
            beats = ("yes" if (feas and c is not None and obj < c) else "no")
            dobj = dz3 = ""
            if mode == "ON" and off[1] is not None and obj is not None:
                dobj = f"{obj - off[1]:+.0f}"
                if off[4] is not None and z3 is not None:
                    dz3 = f"{z3 - off[4]:+.0f}"
            print(f"{inst:<9} {mode:<5} {obj:10.0f} {z1:6.0f} {z2:8.1f} "
                  f"{z3s:>8} {wall:6.1f}  {c:8.0f} {vs:>8}  {str(feas):>5}  "
                  f"{dobj:>9} {dz3:>8}  {beats}")
        print("-" * 114)

    # Summary verdict.
    print("=" * 114)
    print("SUMMARY")
    z1_ok = True             # ON: z1=0 + feasible everywhere
    z3_drop_close = True     # ON: z3 drops on prob_11/17 (the close losses)
    no_regress15 = True      # ON: prob_15 not regressed
    new_beats = []
    for inst in insts:
        off, on = rows[inst]
        of_feas, of_obj, of_z1, _, of_z3, _ = off
        on_feas, on_obj, on_z1, _, on_z3, _ = on
        if on_obj is None or on_z1 is None or abs(on_z1) > 1e-6 or not on_feas:
            z1_ok = False
        if inst in ("prob_11", "prob_17"):
            if of_z3 is None or on_z3 is None or not (on_z3 < of_z3 - 1e-9):
                z3_drop_close = False
        if inst == "prob_15":
            if of_obj is not None and on_obj is not None and on_obj > of_obj + 1e-6:
                no_regress15 = False
        c = competitor.get(inst)
        if on_feas and on_obj is not None and c is not None and on_obj < c:
            new_beats.append(inst)
    print(f"  z1=0 + feasible everywhere ON       : {z1_ok}")
    print(f"  z3 drops on close losses 11/17 ON   : {z3_drop_close}")
    print(f"  prob_15 not regressed ON            : {no_regress15}")
    print(f"  instances now beating competitor ON : "
          f"{new_beats if new_beats else 'none'}")
    success = z1_ok and z3_drop_close and no_regress15
    print(f"  OVERALL SUCCESS                     : {success}")
    print("=" * 114)


if __name__ == "__main__":
    _selftest()
