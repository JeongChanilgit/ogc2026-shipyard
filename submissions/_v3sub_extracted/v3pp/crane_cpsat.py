"""
crane_cpsat.py -- CRANE-AWARE position+timing CP-SAT re-packing pass (one bay).

Generalises the per-bay TIMING oracle (`_cpsat_bay_timing_verified` in the v2
solver) so it chooses POSITIONS as well as entry/exit times.  The timing oracle
keeps positions fixed and precomputes, for every interacting block pair, 5
TIME-INDEPENDENT crane/collision booleans (via the official `check_*` checks) and
turns each into a TIME DISJUNCTION over the integer entry vars.

This file does the same, but with one extra layer of choice: each block gets a
SMALL set of position candidates (a few integer x-anchors at the block's fixed y
and orientation -- the user's "linearise the bay to 1-D" idea).  Optionally
(n_ycand > 0) each ACTIVE block ALSO gets a few integer y-anchors at its current
x/orient -- the user's "x+y simultaneously" lever for crane locks that x-only
moves cannot relieve.  The candidate set is a LINEAR UNION, not a grid product:
{current} u {x-shifted} u {y-shifted}, so the per-block count stays additive
(1 + (n_xcand-1) + n_ycand) instead of K_x * K_y.  Because the candidate set is
tiny and discrete, every crane boolean is STILL precomputable --
now per (pair, candidate-combo).  A CP-SAT selection var `sel[b][ci]` chooses one
candidate per block, and every disjunction is gated on the two relevant selection
vars, so a constraint binds only when both candidates are chosen.

Never-worse by construction:
  * Candidate 0 of every block is its CURRENT pose, so the current solution is
    feasible in the model => CP-SAT optimum tardiness <= current tardiness.
  * We AddHint the current selection + current entry => warm start.
  * Because the crane booleans are precomputed per candidate-combo from the
    OFFICIAL checks, any accepted move is crane-FEASIBLE (unlike a bbox model).

Usage:
    python crane_cpsat.py [prob_name] [bay_id] [time_s] [n_xcand] [n_ycand] [n_ocand]

    prob_name : 'prob_24' etc.       (default 'prob_24')
    bay_id    : int or 'auto'        (default 'auto' = bay with most preferred blocks)
    time_s    : CP-SAT wall limit s  (default 30.0)
    n_xcand   : x-candidates / block (default 5)
    n_ycand   : y-candidates / block (default 0 == byte-identical to x-only)
    n_ocand   : orient-variant candidates / block (default 0 == byte-identical
                to x/y-only).  Each orient variant re-orients the block to an
                alternative orientation and clamps (x, y) into that orient's
                valid range, carrying its OWN shape through precompute + extract.

The candidate set per active block is a LINEAR UNION (not a grid product):
    {current} u {x-shifted} u {y-shifted} u {orient-variants}
so the per-block count stays additive: 1 + (n_xcand-1) + n_ycand + n_ocand.

Examples:
    python crane_cpsat.py prob_24 auto 30 5
    python crane_cpsat.py prob_29 auto 30 5
    python crane_cpsat.py prob_38 auto 30 4 3      # x+y union candidates
    python crane_cpsat.py prob_38 2 60 5 0 2       # x + 2 orient variants
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
# v3pp package: cross-imports are package-relative; do NOT pollute sys.path.
from .temporal_pack import build_subset, seed_order, simulate  # noqa: E402
from .gridmap import BlockShape                                  # noqa: E402
import utils as _utils                                          # noqa: E402
from utils import Bay, Block, check_collisions, check_entry, check_exit  # noqa: E402
from . import xreopt_ref as _xref                               # noqa: E402

# Strict crane co-exit handling: matches the timing oracle's `co=True` branch
# (_CRANE_COEXIT default True), i.e. the strict `+1` disjunction variants.
_CRANE_COEXIT = True

# Total candidate-combo precompute cap.  Above this we shrink candidate lists in
# order o -> y -> x (orientation variants are the most speculative, dropped first).
_COMBO_CAP = 200_000


# ---------------------------------------------------------------------------
# Step A -- per-block position candidates
# ---------------------------------------------------------------------------

def _x_anchors(sh: BlockShape, W: int, n: int) -> list[int]:
    """`n` distinct integer x-anchors evenly across [x_lb, x_ub] (y/orient fixed)."""
    lb = _xref._x_lb(sh)
    ub = _xref._x_ub(sh, W)
    if ub <= lb:
        return [lb]
    if n <= 1:
        return [lb]
    out = []
    for k in range(n):
        xa = int(round(lb + (ub - lb) * k / (n - 1)))
        out.append(max(lb, min(ub, xa)))
    # de-dup, preserve order
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _y_anchors(sh: BlockShape, H: int, n: int) -> list[int]:
    """`n` distinct integer y-anchors evenly across [y_lb, y_ub] (x/orient fixed).

    y_lb = max(0, ceil(-sh.min_y))   (world y >= 0)
    y_ub = max(y_lb, floor(H - sh.max_y))  (world y + max_y <= bay height)
    """
    lb = max(0, int(math.ceil(-sh.min_y - 1e-9)))
    ub = max(lb, int(math.floor(H - sh.max_y + 1e-9)))
    if ub <= lb:
        return [lb]
    if n <= 1:
        return [lb]
    out = []
    for k in range(n):
        ya = int(round(lb + (ub - lb) * k / (n - 1)))
        out.append(max(lb, min(ub, ya)))
    seen = set()
    uniq = []
    for y in out:
        if y not in seen:
            seen.add(y)
            uniq.append(y)
    return uniq


def _tardy_ids(placed, meta) -> set:
    """Block ids that are tardy in the current placement (exit > due)."""
    return {p["id"] for p in placed if p["exit"] > meta[p["id"]][2]}


def _near_tardy(placed, tardy, margin: float) -> set:
    """Ids whose x-bbox is within `margin` of any tardy block's x-bbox."""
    if not tardy:
        return set()
    spans = {}
    for p in placed:
        sh = p["sh"]
        spans[p["id"]] = (p["x"] + sh.min_x, p["x"] + sh.max_x)
    near = set(tardy)
    tspans = [spans[b] for b in tardy]
    for p in placed:
        bid = p["id"]
        if bid in near:
            continue
        x0, x1 = spans[bid]
        for t0, t1 in tspans:
            # gap between intervals (negative = overlap)
            gap = max(t0 - x1, x0 - t1)
            if gap <= margin:
                near.add(bid)
                break
    return near


def _build_candidates(data, placed, meta, W, H, n_xcand, n_ycand, n_ocand,
                      window_tardy_only, near_margin, free_ids=None):
    """For each block build a list of candidate poses (x, y, orient_idx).

    Candidate 0 is ALWAYS the current pose.  Frozen blocks (when windowing) get
    only candidate 0.

    Returns (cands, cand_shapes, tardy, active) where
        cands[bid]       : list[(x, y, orient)]  -- poses, de-duplicated
        cand_shapes[bid] : list[BlockShape]      -- parallel, one per candidate.
    Candidate 0's shape is the block's current shape (p["sh"]).  ORIENTATION
    variants carry their OWN re-oriented BlockShape (different geometry than
    candidate 0), so precompute/extract use the candidate's shape, not a single
    block-level shape.  x/y variants keep the current orient -> share p["sh"].

    LINEAR (union) candidate set, NOT a grid product:
        candidates = {current pose}
                   u {x-shifted (current y, current orient)}   <- n_xcand-1 new
                   u {y-shifted (current x, current orient)}   <- n_ycand   new
                   u {orient-variants (clamped x/y, alt orient)} <- n_ocand  new
    so the per-block count is at most 1 + (n_xcand-1) + n_ycand + n_ocand.
    Identical poses are de-duplicated.

    LNS mode (free_ids not None): ACTIVE = free_ids intersect this bay's ids;
    all other blocks are FROZEN (candidate 0 only).  This OVERRIDES the
    window_tardy_only / near_margin active selection.
    """
    from gridmap import build_shape
    tardy = _tardy_ids(placed, meta)
    if free_ids is not None:
        bay_ids = {p["id"] for p in placed}
        active = set(free_ids) & bay_ids
    elif window_tardy_only:
        active = _near_tardy(placed, tardy, near_margin)
    else:
        active = {p["id"] for p in placed}

    cands = {}
    cand_shapes = {}
    for p in placed:
        bid = p["id"]
        sh = p["sh"]
        cur = (int(p["x"]), int(p["y"]), int(p["orient"]))
        lst = [cur]
        shapes = [sh]
        seen = {cur}
        if bid in active:
            # x-shifted candidates (keep current y + orient) -> share p["sh"].
            # n_xcand <= 0 adds NO x-anchors (skip the loop entirely) so the
            # block keeps only candidate 0 along x -- this is what lets a pure
            # "x-frozen" pass exist (n_xcand=n_ycand=n_ocand=0 => candidate 0
            # only => positions fully frozen => timing-only oracle).  For
            # n_xcand >= 1 the loop runs exactly as before (byte-identical).
            if n_xcand > 0:
                for xa in _x_anchors(sh, W, n_xcand):
                    pose = (int(xa), int(p["y"]), int(p["orient"]))
                    if pose not in seen:
                        seen.add(pose)
                        lst.append(pose)
                        shapes.append(sh)
            # y-shifted candidates (keep current x + orient) -- the x+y lever.
            if n_ycand > 0:
                for ya in _y_anchors(sh, H, n_ycand):
                    pose = (int(p["x"]), int(ya), int(p["orient"]))
                    if pose not in seen:
                        seen.add(pose)
                        lst.append(pose)
                        shapes.append(sh)
            # orient-variant candidates (alt orientation, x/y clamped into the
            # new orient's valid range) -- the x/y/o lever.  Each carries its
            # OWN re-oriented shape.
            if n_ocand > 0:
                n_orients = len(data["blocks"][bid]["shape"])
                cur_o = int(p["orient"])
                added_o = 0
                for o2 in range(n_orients):
                    if added_o >= n_ocand:
                        break
                    if o2 == cur_o:
                        continue
                    sh2 = build_shape(bid, data["blocks"][bid], o2, sh.scale)
                    # clamp current x/y into the o2-shape's valid range
                    x_lb = _xref._x_lb(sh2)
                    x_ub = _xref._x_ub(sh2, W)
                    y_lb = max(0, int(math.ceil(-sh2.min_y - 1e-9)))
                    y_ub = max(y_lb, int(math.floor(H - sh2.max_y + 1e-9)))
                    x2 = max(x_lb, min(x_ub, int(p["x"])))
                    y2 = max(y_lb, min(y_ub, int(p["y"])))
                    pose = (x2, y2, o2)
                    added_o += 1   # count the attempt (caps work even if dup)
                    if pose not in seen:
                        seen.add(pose)
                        lst.append(pose)
                        shapes.append(sh2)
        cands[bid] = lst
        cand_shapes[bid] = shapes
    return cands, cand_shapes, tardy, active


# ---------------------------------------------------------------------------
# Step B -- precompute crane/collision booleans per (pair, candidate-combo)
# ---------------------------------------------------------------------------

def _precompute_combos(data, bay, placed, cands, free_ids=None):
    """Return (pair_booleans, n_combos, n_pose_calls).

    pair_booleans : dict (a, b, ci_a, ci_b) -> (coll, ba_e, ab_e, ba_x, ab_x)
                    a < b (block ids).  All-False combos are skipped.
    A small pose -> Block cache avoids re-instantiating identical poses.

    LNS mode (free_ids not None): SKIP frozen-frozen pairs entirely.  Both
    blocks are at their fixed current pose AND fixed current time, so their
    mutual crane/collision constraints are constant-true (the input solution is
    already feasible) and add nothing to the model.  Free-free and free-frozen
    pairs are still precomputed.
    """
    ids = [p["id"] for p in placed]
    blocks_data = data["blocks"]

    # Block-object cache keyed by (bid, pose) so frozen candidate-0 poses
    # (which repeat across pairs) are built once.
    blk_cache: dict = {}

    def _blk(bid, pose):
        key = (bid, pose)
        bo = blk_cache.get(key)
        if bo is None:
            x, y, o = pose
            bo = Block(block_id=bid, block_data=blocks_data[bid],
                       x=x, y=y, orient_idx=o)
            blk_cache[key] = bo
        return bo

    pair_bools: dict = {}
    n_combos = 0
    for ia in range(len(ids)):
        a = ids[ia]
        ca_list = cands[a]
        for ib in range(ia + 1, len(ids)):
            b = ids[ib]
            # LNS: skip frozen-frozen pairs (fixed pose + fixed time => constant
            # feasible, contribute nothing).
            if free_ids is not None and a not in free_ids and b not in free_ids:
                continue
            cb_list = cands[b]
            for ci_a, pose_a in enumerate(ca_list):
                blk_a = _blk(a, pose_a)
                for ci_b, pose_b in enumerate(cb_list):
                    blk_b = _blk(b, pose_b)
                    n_combos += 1
                    coll = bool(check_collisions(bay, [blk_a, blk_b]))
                    ba_e = bool(check_entry(bay, [blk_b], blk_a, fast=True))
                    ab_e = bool(check_entry(bay, [blk_a], blk_b, fast=True))
                    ba_x = bool(check_exit(bay, [blk_b], blk_a, fast=True))
                    ab_x = bool(check_exit(bay, [blk_a], blk_b, fast=True))
                    if coll or ba_e or ab_e or ba_x or ab_x:
                        pair_bools[(a, b, ci_a, ci_b)] = (
                            coll, ba_e, ab_e, ba_x, ab_x)
    return pair_bools, n_combos, len(blk_cache)


def _count_combos(cands, ids) -> int:
    tot = 0
    for ia in range(len(ids)):
        a = ids[ia]
        na = len(cands[a])
        for ib in range(ia + 1, len(ids)):
            tot += na * len(cands[ids[ib]])
    return tot


# ---------------------------------------------------------------------------
# Core: crane-aware position+timing re-pack of one bay
# ---------------------------------------------------------------------------

def crane_repack_bay(data, bay_id, placed, time_s,
                     n_xcand=5, n_ycand=0, n_ocand=0, use_orient=False,
                     window_tardy_only=True, num_workers=4,
                     near_margin=8.0, free_ids=None):
    """Crane-aware position+timing CP-SAT re-pack of a single bay.

    Parameters
    ----------
    data    : full instance dict (needs data["blocks"], data["bays"]).
    bay_id  : target bay index.
    placed  : list of placement dicts {id, sh, x, y, orient, entry, exit, world}.
    time_s  : CP-SAT wall limit (seconds).
    free_ids: None  -> EXISTING behaviour (byte-identical).
              set   -> LNS mode.  ACTIVE = free_ids intersect this bay's ids:
                       only those blocks get multiple candidates + a free `entry`
                       IntVar + a tardy term.  ALL OTHER blocks are FROZEN to
                       their CURRENT pose AND current entry/exit (treated as
                       integer CONSTANTS, no NewIntVar).  Frozen-frozen pairs are
                       skipped in precompute; free-frozen pairs bind the free
                       block's entry against the frozen block's CONSTANT time.
                       Never-worse holds: each free block's candidate 0 = current
                       pose hinted with current entry, and frozen blocks are
                       unchanged, so the whole-bay solution is never worse.

    Returns (new_placed_or_None, status_str, wall, info).
      new_placed : same shape as `placed` with updated x/orient/entry/exit/world
                   for blocks that moved, or None on solver failure.
      info       : dict with diagnostics (n_blocks, n_cands_total, n_combos,
                   precompute_wall, cpsat_wall, ...).
    """
    info = {
        "bay_id": bay_id, "n_blocks": len(placed), "n_cands_total": 0,
        "n_combos": 0, "n_stored": 0, "precompute_wall": 0.0,
        "cpsat_wall": 0.0, "status": "EMPTY", "shrunk": False,
        "n_xcand": n_xcand, "n_ycand": n_ycand, "n_ocand": n_ocand,
        "n_xcands_added": 0, "n_ycands_added": 0, "n_ocands_added": 0,
    }
    if not placed:
        return [], "EMPTY", 0.0, info

    try:
        from ortools.sat.python import cp_model
    except Exception:
        info["status"] = "NO_ORTOOLS"
        return None, "NO_ORTOOLS", 0.0, info

    meta = {p["id"]: (math.ceil(_blk_R(data, p["id"]) - 1e-9),
                      int(round(p["exit"] - p["entry"])),
                      int(_blk_D(data, p["id"])))
            for p in placed}
    W = int(data["bays"][bay_id]["width"])
    H = int(data["bays"][bay_id]["height"])
    bay = Bay.from_dict(data["bays"][bay_id], bay_id)
    ids = [p["id"] for p in placed]

    # -- Step A: candidates -------------------------------------------------
    cands, cand_shapes, tardy, active = _build_candidates(
        data, placed, _meta_RPD(data, placed), W, H,
        n_xcand, n_ycand, n_ocand, window_tardy_only, near_margin, free_ids)
    # `active` is the set of FREE (variable) blocks; everything else is FROZEN.
    frozen = {p["id"] for p in placed} - active

    # cost guard: shrink candidate lists if combo count blows the cap.  Drop in
    # order o -> y -> x (orientation variants are the most speculative), logging
    # which we reduced.
    nx, ny, no = n_xcand, n_ycand, n_ocand
    while _count_combos(cands, ids) > _COMBO_CAP and (nx > 1 or ny > 0 or no > 0):
        if no > 0:
            no -= 1
            shrunk_which = "n_ocand"
            shrunk_to = no
        elif ny > 0:
            ny -= 1
            shrunk_which = "n_ycand"
            shrunk_to = ny
        else:
            nx -= 1
            shrunk_which = "n_xcand"
            shrunk_to = nx
        info["shrunk"] = True
        cands, cand_shapes, tardy, active = _build_candidates(
            data, placed, _meta_RPD(data, placed), W, H,
            nx, ny, no, window_tardy_only, near_margin, free_ids)
        frozen = {p["id"] for p in placed} - active
        print(f"  [guard] combo count exceeded cap {_COMBO_CAP}; "
              f"shrunk {shrunk_which} -> {shrunk_to}", flush=True)

    # record the realised candidate breakdown (union, not grid).  Classify each
    # non-current candidate by which axis it varies: orient first (different o),
    # then y (same orient/x, different y), then x.
    nx_add = ny_add = no_add = 0
    for p in placed:
        bid = p["id"]
        cx, cy, co_ = int(p["x"]), int(p["y"]), int(p["orient"])
        for (x, y, o) in cands[bid]:
            if (x, y, o) == (cx, cy, co_):
                continue
            if o != co_:
                no_add += 1
            elif y != cy:
                ny_add += 1
            else:
                nx_add += 1
    info["n_xcands_added"] = nx_add
    info["n_ycands_added"] = ny_add
    info["n_ocands_added"] = no_add
    info["n_cands_total"] = sum(len(c) for c in cands.values())

    # -- Step B: precompute crane booleans ----------------------------------
    t0 = time.monotonic()
    pair_bools, n_combos, n_blk = _precompute_combos(
        data, bay, placed, cands, free_ids)
    info["precompute_wall"] = time.monotonic() - t0
    info["n_combos"] = n_combos
    info["n_stored"] = len(pair_bools)
    _frz = f"frozen={len(frozen)} " if free_ids is not None else ""
    print(f"  [precompute] blocks={len(placed)} active={len(active)} "
          f"{_frz}"
          f"tardy={len(tardy)} cands_total={info['n_cands_total']} "
          f"(x+{info['n_xcands_added']} y+{info['n_ycands_added']} "
          f"o+{info['n_ocands_added']}) "
          f"combos={n_combos} stored={len(pair_bools)} "
          f"poses={n_blk} wall={info['precompute_wall']:.2f}s", flush=True)

    # -- Step C: CP-SAT model -----------------------------------------------
    m = cp_model.CpModel()
    R = {b: meta[b][0] for b in ids}
    P = {b: meta[b][1] for b in ids}
    D = {b: meta[b][2] for b in ids}
    cur_entry = {p["id"]: int(p["entry"]) for p in placed}

    cur_makespan = max(int(p["exit"]) for p in placed)
    maxP = max(P[b] for b in ids)
    H = cur_makespan + maxP

    # FREE blocks get selection + entry vars; FROZEN blocks (LNS only) keep
    # candidate 0 and their CURRENT entry as an integer CONSTANT.
    #
    # NON-LNS (free_ids is None): EVERY block is free, exactly as before -- the
    # original model gave a sel var, entry IntVar, tardy term and hint to all
    # blocks (the `active` set only controlled candidate COUNT, not whether a
    # block had vars).  So is_free is uniformly True => byte-identical model.
    #
    # LNS (free_ids set): only `active` (= free_ids in this bay) blocks are free;
    # the rest are frozen to candidate 0 + current entry/exit constants.
    if free_ids is None:
        is_free = {b: True for b in ids}
    else:
        is_free = {b: (b in active) for b in ids}

    # selection vars: one candidate chosen per FREE block (frozen blocks have
    # no sel var -- they are pinned to candidate 0 = current pose).
    sel = {}
    for p in placed:
        b = p["id"]
        if not is_free[b]:
            continue
        nb = len(cands[b])
        sel[b] = [m.NewBoolVar(f"sel_{b}_{ci}") for ci in range(nb)]
        m.AddExactlyOne(sel[b])

    # entry: FREE -> IntVar; FROZEN -> integer constant (current entry).
    e = {}
    for b in ids:
        if is_free[b]:
            e[b] = m.NewIntVar(R[b], H, f"e_{b}")
        else:
            e[b] = cur_entry[b]      # integer constant
    co = _CRANE_COEXIT

    # gated disjunctions, one per stored (pair, candidate-combo).  The gate only
    # contains selection vars of FREE blocks; a frozen block's candidate is
    # fixed (ci == 0) so it needs no gate literal.  A frozen block's entry/exit
    # enter the expressions as integer CONSTANTS.
    for (a, b, ci_a, ci_b), (coll, ba_e, ab_e, ba_x, ab_x) in pair_bools.items():
        ae, be = e[a], e[b]
        ax = ae + P[a]
        bx = be + P[b]
        gate = []
        if is_free[a]:
            gate.append(sel[a][ci_a])
        if is_free[b]:
            gate.append(sel[b][ci_b])
        if coll:
            # forbid time-overlap: a before b OR b before a
            l1 = m.NewBoolVar("")
            l2 = m.NewBoolVar("")
            m.Add(ax <= be).OnlyEnforceIf([l1] + gate)
            m.Add(bx <= ae).OnlyEnforceIf([l2] + gate)
            m.AddBoolOr([l1, l2]).OnlyEnforceIf(gate)
            # collision subsumes the crane configs for this pose-pair
            continue
        if ba_e:  # b present at a's entry forbidden
            l1 = m.NewBoolVar("")
            l2 = m.NewBoolVar("")
            m.Add(ae <= be - 1).OnlyEnforceIf([l1] + gate)
            m.Add(ae >= bx).OnlyEnforceIf([l2] + gate)
            m.AddBoolOr([l1, l2]).OnlyEnforceIf(gate)
        if ab_e:  # a present at b's entry forbidden
            l1 = m.NewBoolVar("")
            l2 = m.NewBoolVar("")
            m.Add(be <= ae - 1).OnlyEnforceIf([l1] + gate)
            m.Add(be >= ax).OnlyEnforceIf([l2] + gate)
            m.AddBoolOr([l1, l2]).OnlyEnforceIf(gate)
        if ba_x:  # b present at a's exit forbidden
            l1 = m.NewBoolVar("")
            l2 = m.NewBoolVar("")
            m.Add(ax <= be).OnlyEnforceIf([l1] + gate)
            m.Add(ax >= (bx + 1) if co else (bx)).OnlyEnforceIf([l2] + gate)
            m.AddBoolOr([l1, l2]).OnlyEnforceIf(gate)
        if ab_x:  # a present at b's exit forbidden
            l1 = m.NewBoolVar("")
            l2 = m.NewBoolVar("")
            m.Add(bx <= ae).OnlyEnforceIf([l1] + gate)
            m.Add(bx >= (ax + 1) if co else (ax)).OnlyEnforceIf([l2] + gate)
            m.AddBoolOr([l1, l2]).OnlyEnforceIf(gate)

    # tardiness + objective -- only FREE blocks contribute (frozen tardiness is
    # a constant: their entry/exit are fixed, so minimising Sum over free blocks
    # is equivalent to minimising whole-bay tardiness up to that constant).
    tard = []
    for b in ids:
        if not is_free[b]:
            continue
        tb = m.NewIntVar(0, H, f"t_{b}")
        m.Add(tb >= e[b] + P[b] - D[b])
        tard.append(tb)
    m.Minimize(sum(tard))

    # warm start: current candidate (index 0) + current entry, FREE blocks only
    # (frozen blocks have no vars).  candidate 0 == current pose => the current
    # solution is representable => CP-SAT optimum tardiness <= current.
    for p in placed:
        b = p["id"]
        if not is_free[b]:
            continue
        m.AddHint(sel[b][0], 1)
        m.AddHint(e[b], cur_entry[b])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_s)
    solver.parameters.num_search_workers = int(num_workers)
    solver.parameters.log_search_progress = False

    t0 = time.monotonic()
    status_code = solver.Solve(m)
    info["cpsat_wall"] = time.monotonic() - t0

    from ortools.sat.python.cp_model import OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN
    status_map = {OPTIMAL: "OPTIMAL", FEASIBLE: "FEASIBLE",
                  INFEASIBLE: "INFEASIBLE", UNKNOWN: "UNKNOWN"}
    status_str = status_map.get(status_code, f"STATUS_{status_code}")
    info["status"] = status_str
    obj = solver.ObjectiveValue() if status_code in (OPTIMAL, FEASIBLE) else "?"
    print(f"  [CP-SAT] status={status_str} obj={obj} "
          f"wall={info['cpsat_wall']:.2f}s", flush=True)

    if status_code not in (OPTIMAL, FEASIBLE):
        return None, status_str, info["cpsat_wall"], info

    # -- Step D: extract + rebuild ------------------------------------------
    # FREE blocks take the solver's chosen candidate + entry; FROZEN blocks (LNS)
    # are copied UNCHANGED (no sel/entry var exists for them).
    from shapely.affinity import translate
    new_placed = []
    for p in placed:
        b = p["id"]
        if not is_free[b]:
            new_placed.append(dict(p))   # frozen: identical record
            continue
        ci = next((k for k in range(len(sel[b]))
                   if solver.Value(sel[b][k]) == 1), 0)
        new_x, new_y, new_o = cands[b][ci]
        # use THIS candidate's shape (orient variants carry their own re-oriented
        # BlockShape; candidate 0 / x/y variants reuse p["sh"]).
        sh = cand_shapes[b][ci]
        new_entry = int(solver.Value(e[b]))
        new_exit = new_entry + P[b]
        new_world = {
            l: translate(sh.layers[l].poly, xoff=new_x, yoff=new_y)
            for l in range(sh.n_layers)
        }
        new_placed.append({
            **p,
            "sh": sh,
            "x": new_x,
            "y": new_y,
            "orient": new_o,
            "entry": new_entry,
            "exit": new_exit,
            "world": new_world,
        })
    return new_placed, status_str, info["cpsat_wall"], info


# ---------------------------------------------------------------------------
# small helpers to read R/P/D off the instance for a block id
# ---------------------------------------------------------------------------

def _blk_R(data, bid):
    return data["blocks"][bid].get("release_time", 0)


def _blk_D(data, bid):
    return data["blocks"][bid].get("due_date", 0)


def _meta_RPD(data, placed):
    """{bid: (R, P, D)} using observed greedy P (exit-entry) like the oracle."""
    return {p["id"]: (data["blocks"][p["id"]].get("release_time", 0),
                      int(round(p["exit"] - p["entry"])),
                      data["blocks"][p["id"]].get("due_date", 0))
            for p in placed}


# ---------------------------------------------------------------------------
# CLI / driver
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    prob = args[0] if len(args) > 0 else "prob_24"
    bay_a = args[1] if len(args) > 1 else "auto"
    ts = float(args[2]) if len(args) > 2 else 30.0
    n_xcand = int(args[3]) if len(args) > 3 else 5
    n_ycand = int(args[4]) if len(args) > 4 else 0
    n_ocand = int(args[5]) if len(args) > 5 else 0

    inst = _xref._find_inst(prob)
    if inst is None:
        print(f"Instance not found: {prob}", file=sys.stderr)
        sys.exit(1)

    data = json.load(open(inst, encoding="utf-8"))
    bays = data["bays"]
    blocks = data["blocks"]
    m = len(bays)

    # bay auto-pick: highest greedy_z1 bay would be ideal, but cheaply we mirror
    # xreopt_ref (most-preferred bay) unless an explicit id is given.
    pref = [max(range(m), key=lambda j: blocks[i]["bay_preferences"][j])
            for i in range(len(blocks))]
    bay_counts = [pref.count(j) for j in range(m)]
    if bay_a in ("auto", "None", "none", ""):
        bay_id = max((j for j in range(m) if bay_counts[j] > 0),
                     key=lambda j: bay_counts[j])
    else:
        bay_id = int(bay_a)

    W = bays[bay_id]["width"]
    H = bays[bay_id]["height"]

    print(f"\n{'='*64}", flush=True)
    print(f"Instance : {os.path.basename(inst)}", flush=True)
    print(f"Bay {bay_id}   ({W}x{H}, {bay_counts[bay_id]} preferred blocks)", flush=True)
    print(f"CP-SAT limit={ts}s  n_xcand={n_xcand}  n_ycand={n_ycand}  "
          f"n_ocand={n_ocand}", flush=True)
    print(f"{'='*64}", flush=True)

    # greedy layout on the chosen bay
    t0 = time.monotonic()
    sub = build_subset(inst, bay_id, 2, geom="poly")
    order = seed_order(sub, "edd")
    placed, greedy_z1 = simulate(sub, order, allow_stack=False, fit=True)
    greedy_wall = time.monotonic() - t0
    print(f"Greedy: {len(placed)} blocks, Z1={greedy_z1}, wall={greedy_wall:.1f}s",
          flush=True)
    if not placed:
        print("No greedy placements -- skip.", flush=True)
        return

    meta = sub["meta"]

    # crane-aware re-pack
    new_placed, status, cpsat_wall, info = crane_repack_bay(
        data, bay_id, placed, ts,
        n_xcand=n_xcand, n_ycand=n_ycand, n_ocand=n_ocand)

    if new_placed is None:
        new_placed = placed
        new_z1 = greedy_z1
    else:
        new_z1 = sum(max(0, p["exit"] - meta[p["id"]][2]) for p in new_placed)

    feasible = _xref._check_bay_feasibility(data, bay_id, new_placed)

    delta = new_z1 - greedy_z1
    dpct = (delta / greedy_z1 * 100.0) if greedy_z1 > 0 else 0.0

    print(f"\n{'='*64}", flush=True)
    print(f"SUMMARY  bay={bay_id}  blocks={info['n_blocks']}  "
          f"n_xcand={info['n_xcand']}  n_ycand={info['n_ycand']}  "
          f"n_ocand={info['n_ocand']}", flush=True)
    print(f"  cands_total={info['n_cands_total']} "
          f"(x+{info['n_xcands_added']} y+{info['n_ycands_added']} "
          f"o+{info['n_ocands_added']})  "
          f"combos={info['n_combos']}  stored={info['n_stored']}", flush=True)
    print(f"  precompute_wall={info['precompute_wall']:.2f}s  "
          f"cpsat_wall={cpsat_wall:.2f}s  status={status}", flush=True)
    print(f"  greedy_z1={greedy_z1} -> new_z1={new_z1}  "
          f"delta={delta:+d} ({dpct:+.1f}%)  "
          f"single-bay-feasible={feasible}", flush=True)
    print(f"{'='*64}", flush=True)


if __name__ == "__main__":
    main()
