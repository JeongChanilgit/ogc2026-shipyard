# perbay.py
#
# OGC 2026 -- The Grand Shipyard Puzzle
# Per-bay JOINT (x, y, orientation, entry/exit) CP-SAT placement+timing engine.
#
# This is a GATED best-of CANDIDATE.  A separate integration in myalgorithm.py
# adopts its output only if the official `check_feasibility` passes AND the
# objective strictly improves, all wrapped in try/except.  Therefore this engine:
#   * NEVER raises to the caller (everything wrapped in try/except),
#   * is strictly deadline-bounded (time.monotonic()), and
#   * in the worst case returns the input solution UNCHANGED (identity).
#
# Why "joint" (unlike myalgorithm._cpsat_bay_timing_verified, which fixes the
# layout and re-times only): here we let each block's POSITION (x,y) and
# ORIENTATION move as well, so a bay whose tardiness is gated by a crane/
# collision conflict at the fixed layout can sometimes escape it by sliding a
# block apart in space rather than only deferring it in time.
#
# Bay ASSIGNMENT stays fixed, so Z2 (load imbalance) and Z3 (preference) are
# provably invariant -- only per-bay tardiness Z1 changes.  We only touch bays
# whose current tardiness > 0 (repositioning can never push Z1 below 0).
#
# SAFETY MODEL (verified from utils.py, see CLAUDE.md feasibility semantics):
#   If two co-present blocks' bounding boxes do NOT overlap in (x,y), then no
#   collision and no crane obstruction can fire at ANY layer.  So enforcing
#   "for every pair: bbox-separated in x OR y, OR time-disjoint" GUARANTEES
#   feasibility stages 2/3/4 for both single- and multi-layer blocks.  This is
#   conservative (it forbids some legal crane-stacking) but always feasible.
#
# The bay-bounds (stage 4 containment) is enforced via xl+wv<=W, yl+hv<=H with
# xl,yl >= 0.  Stage 1 (orient in range, exit-entry>=P, entry>=release) is
# enforced by construction (oi in [0,O-1], exit=entry+P, entry>=R).  Stage 5
# (EXIT-before-ENTRY within a timestamp) is handled by _build_operations.

from __future__ import annotations

import math
import os
import sys
import time


# -----------------------------------------------------------------------------
# Tiny env helpers -- replicated inline (NOT imported from myalgorithm) to avoid
# importing myalgorithm at module load time (circular import: myalgorithm will
# import perbay).  Behaviour is bit-identical to myalgorithm._env_* .  All three
# never raise; an unset/unparseable var returns the default, so absent env is
# exactly what ships.
# -----------------------------------------------------------------------------
def _env_on(name: str, default: bool) -> bool:
    try:
        v = os.environ.get(name, "").strip().lower()
        if not v:
            return default
        return v not in ("0", "false", "off", "no")
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return float(v)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return int(float(v))
    except Exception:
        return default


def _dbg(msg: str) -> None:
    """Stderr trace, gated by OGC_PERBAY_DEBUG (default off).  Never raises."""
    try:
        if _env_on("OGC_PERBAY_DEBUG", False):
            sys.stderr.write("[perbay] " + msg + "\n")
            sys.stderr.flush()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Geometry: (anchor x, y, orient o) -> bbox in bay coordinates.
#
# Derived from utils.Block.__post_init__:
#   layers = shape[o]["layers"]; ref = layers[0][0]  (first vertex, first layer)
#   each local vertex (vx, vy) maps to world (vx + x - ref_x, vy + y - ref_y).
# Hence the world bbox-min corner is:
#   bbox_left   = local_min_x + (x - ref_x) = x + (local_min_x - ref_x)
#   bbox_bottom = local_min_y + (y - ref_y) = y + (local_min_y - ref_y)
# So with
#   offminx[o] = local_min_x - ref_x
#   offminy[o] = local_min_y - ref_y
# we have  bbox_left = anchor_x + offminx[o]   <=>   anchor_x = bbox_left - offminx[o]
# and width  = local_max_x - local_min_x, height = local_max_y - local_min_y
# (both translation-invariant).
#
# We do NOT assume ref == (0,0) (utils' generator guarantees it, but we compute
# offsets explicitly and a sanity check below catches any mismatch).
# -----------------------------------------------------------------------------
def _orient_geom(block_data: dict, o: int):
    """Return (w, h, offminx, offminy) as ints for orientation o.

    The CRITICAL invariant (see BUG 1): the integer bbox we hand to CP-SAT must
    CONSERVATIVELY CONTAIN the true FLOAT polygon that utils' checker measures.
    utils does NOT round vertices -- Block.__post_init__ translates the float
    verts by (anchor - ref) where anchor is integer and ref is float, and
    bounding_rect()/contains_block()/_bb_overlap all operate on those FLOAT
    bboxes.  So in world coords the true footprint span is
        world_min_x = anchor_x + (min_x - ref_x)
        world_max_x = anchor_x + (max_x - ref_x)
    If we rounded the offset/width (the old code did int(round(...))), an
    integer box could be SMALLER than the float polygon, so integer abutment
    (xl_a + w_a == xl_b) would still leave a sub-unit float overlap (stage-2
    collision) and a box flush to the bay edge could spill over (stage-4
    boundary).  We therefore FLOOR the min offset and CEIL the max extent so:
        bbox_left  = anchor_x + offminx <= world_min_x   (offminx = floor(min-ref))
        bbox_right = anchor_x + offminx + w >= world_max_x  (w via ceil(max-ref))
    Hence integer non-overlap => float non-overlap, and integer in-bounds =>
    float in-bounds.

    offminx/offminy satisfy bbox_left = anchor_x + offminx <=> anchor_x =
    bbox_left - offminx.  w/h are the conservative (outward-rounded) extents."""
    raw_layers = block_data["shape"][o]["layers"]
    layers = [list(l) for l in raw_layers if l]
    if not layers:
        # Degenerate shape: utils falls back to a 1x1 box anchored at (x,y).
        return 1, 1, 0, 0
    ref_x, ref_y = layers[0][0]
    all_verts = [v for l in layers for v in l]
    min_x = min(v[0] for v in all_verts)
    min_y = min(v[1] for v in all_verts)
    max_x = max(v[0] for v in all_verts)
    max_y = max(v[1] for v in all_verts)
    # Conservative outward rounding, measured from the same ref the checker uses.
    offminx = int(math.floor(min_x - ref_x))
    offminy = int(math.floor(min_y - ref_y))
    w = int(math.ceil(max_x - ref_x)) - offminx
    h = int(math.ceil(max_y - ref_y)) - offminy
    # utils never produces a zero-area footprint for a real layer, but guard so
    # the CP-SAT element channel always has positive extent.
    if w <= 0:
        w = 1
    if h <= 0:
        h = 1
    return w, h, offminx, offminy


# -----------------------------------------------------------------------------
# Per-bay joint CP-SAT solve.
# -----------------------------------------------------------------------------
def _solve_bay(W, H, ids, recs, blocks, cur_bay_tard, Hmax, bay_budget,
               deadline_for_bay, info=None, movable=None):
    """Jointly re-optimize (x, y, orient, entry) for one bay's blocks to minimize
    this bay's total tardiness, subject to the conservative pairwise separation
    that guarantees feasibility.  Warm-started from the current layout.

    `movable` (optional): a set/iterable of block ids whose (x,y,orient,entry) are
    FREE; all OTHER blocks in the bay are FROZEN (their position/orient/entry stay
    at the input layout, contributing only as constant obstacles).  This is the
    "B3 + push" mode (user 2026-06-19): only the TARDY blocks get spatial freedom
    to slide into a crane-clear free spot, while the rest are fixed -> the model is
    O(|movable|*n) instead of O(n^2), so it stays tractable on the LARGE set2 bays
    that full-joint perbay skips, and CP-SAT (far fewer free vars) finds a better
    feasible point in budget.  movable=None (default) -> ALL movable = the original
    full-joint behaviour, byte-identical.

    Returns a dict {block_id: record} for the WHOLE bay if a strictly lower bay
    tardiness was found, else None.  Never raises (returns None on any error).

    `info` (optional, telemetry-only): if a dict is passed, the outcome is
    recorded into it WITHOUT changing the return value -- keys "status" (one of
    "improved"/"noop"/"skipped_oob"/"error"), "new_tard" (int or None), and
    "err" (str or None).  When `info` is None (the default, i.e. absent
    OGC_PERBAY_LOG path) this is bit-identical to the original behaviour."""
    def _rec(status, new_tard=None, err=None):
        # Best-effort telemetry stamp; never affects the return value.
        try:
            if info is not None:
                info["status"] = status
                info["new_tard"] = new_tard
                info["err"] = err
        except Exception:
            pass
    try:
        from ortools.sat.python import cp_model
    except Exception:
        _rec("error", err="ortools cp_model import failed")
        return None
    try:
        m = cp_model.CpModel()
        mov = set(ids) if movable is None else set(movable)

        # Per-block precomputation: per-orientation geometry + warm-start bbox.
        geom = {}          # b -> list over o of (w, h, offminx, offminy)
        Wv = {}; Hv = {}   # element-channelled width/height vars
        xl = {}; yl = {}   # bbox-left / bbox-bottom IntVars
        oi = {}            # orientation IntVar
        entry = {}; tard = {}
        P = {}; R = {}; D = {}
        hint_o = {}; hint_xl = {}; hint_yl = {}; hint_e = {}

        for b in ids:
            blk = blocks[b]
            P[b] = int(blk["processing_time"])
            R[b] = int(blk["release_time"])
            D[b] = int(blk["due_date"])
            O_b = len(blk["shape"])
            gl = [_orient_geom(blk, o) for o in range(O_b)]
            geom[b] = gl
            w_list = [g[0] for g in gl]
            h_list = [g[1] for g in gl]

            rec = recs[b]
            ro = int(rec["orient_idx"])
            if ro < 0 or ro >= O_b:
                ro = 0
            rw, rh, roffx, roffy = gl[ro]
            # Reconstruct warm-start bbox from the anchor via our formula.
            rbx = int(round(rec["x"])) + roffx
            rby = int(round(rec["y"])) + roffy
            # SANITY: the warm-start layout is feasible, so its bbox MUST lie in
            # [0,W] x [0,H].  If not, our offset formula is wrong -> bail (the
            # caller falls back to the unchanged solution).
            if not (0 <= rbx and rbx + rw <= W and 0 <= rby and rby + rh <= H):
                _dbg(f"    _solve_bay: warm-start block {b} conservative bbox "
                     f"({rbx},{rby})+({rw},{rh}) out of bay {W}x{H} -> skip bay")
                _rec("skipped_oob",
                     err=f"warm-start block {b} bbox out of bay {W}x{H}")
                return None

            if b not in mov:
                # FROZEN obstacle: position/orient/entry are CONSTANTS (the input
                # layout).  Store ints in the same dicts; the pairwise loop and
                # objective accept mixed var/const transparently.
                oi[b] = ro
                Wv[b] = rw; Hv[b] = rh
                xl[b] = rbx; yl[b] = rby
                entry[b] = int(rec["entry_time"])
                tard[b] = max(0, entry[b] + P[b] - D[b])
                continue

            oi[b] = m.NewIntVar(0, O_b - 1, f"o_{b}")
            Wv[b] = m.NewIntVar(min(w_list), max(w_list), f"w_{b}")
            Hv[b] = m.NewIntVar(min(h_list), max(h_list), f"h_{b}")
            m.AddElement(oi[b], w_list, Wv[b])
            m.AddElement(oi[b], h_list, Hv[b])

            xl[b] = m.NewIntVar(0, W, f"xl_{b}")
            yl[b] = m.NewIntVar(0, H, f"yl_{b}")
            m.Add(xl[b] + Wv[b] <= W)
            m.Add(yl[b] + Hv[b] <= H)

            entry[b] = m.NewIntVar(R[b], Hmax, f"e_{b}")
            tard[b] = m.NewIntVar(0, Hmax, f"t_{b}")
            m.Add(tard[b] >= entry[b] + P[b] - D[b])

            hint_o[b] = ro
            hint_xl[b] = rbx
            hint_yl[b] = rby
            hint_e[b] = int(rec["entry_time"])

        # Pairwise conservative separation: for every pair (a, b), a<b, require
        # one of the 6 disjuncts to hold.  bbox-separated in x or y at EVERY
        # instant guarantees no collision/crane obstruction; OR the two are
        # time-disjoint (one finishes before the other starts).
        idl = list(ids)
        for i in range(len(idl)):
            a = idl[i]
            ea = entry[a]; ax = ea + P[a]
            for k in range(i + 1, len(idl)):
                b = idl[k]
                # Both FROZEN -> already non-overlapping in the input layout, so no
                # disjunction needed (this is the O(n^2) -> O(|mov|*n) saving).
                if a not in mov and b not in mov:
                    continue
                eb = entry[b]; bx = eb + P[b]
                sx_ab = m.NewBoolVar("")   # a entirely left of b
                sx_ba = m.NewBoolVar("")   # b entirely left of a
                sy_ab = m.NewBoolVar("")   # a entirely below b
                sy_ba = m.NewBoolVar("")   # b entirely below a
                st_ab = m.NewBoolVar("")   # a finishes before b starts
                st_ba = m.NewBoolVar("")   # b finishes before a starts
                m.Add(xl[a] + Wv[a] <= xl[b]).OnlyEnforceIf(sx_ab)
                m.Add(xl[b] + Wv[b] <= xl[a]).OnlyEnforceIf(sx_ba)
                m.Add(yl[a] + Hv[a] <= yl[b]).OnlyEnforceIf(sy_ab)
                m.Add(yl[b] + Hv[b] <= yl[a]).OnlyEnforceIf(sy_ba)
                m.Add(eb >= ax).OnlyEnforceIf(st_ab)   # b starts at/after a exit
                m.Add(ea >= bx).OnlyEnforceIf(st_ba)   # a starts at/after b exit
                m.AddBoolOr([sx_ab, sx_ba, sy_ab, sy_ba, st_ab, st_ba])

        # ---------------------------------------------------------------------
        # T6 crane-stacking (OPTIONAL, behind OGC_PERBAY_CRANE, default OFF).
        # ---------------------------------------------------------------------
        if _env_on("OGC_PERBAY_CRANE", False):
            # TODO(v2): allow SAFE multi-layer LIFO crane co-presence instead of
            # the conservative all-separated rule above.  For a footprint-
            # overlapping multi-layer pair whose layer structures NEST (the
            # smaller-footprint block sits on top within the larger's footprint
            # at every shared layer), the crane j>=k rule permits a LIFO nesting
            # entry_b <= entry_a AND exit_a <= exit_b (b fully envelops a in
            # time), which would be added as an EXTRA reified disjunct alongside
            # the 6 separation disjuncts.
            #
            # NOT IMPLEMENTED here, and the active path remains the conservative
            # baseline, because deciding "do the layers nest?" depends on the
            # CHOSEN orientation AND the (x,y) offsets of BOTH blocks -- which are
            # themselves decision variables in this joint model -- so the
            # nesting predicate cannot be precomputed (as it can in the
            # fixed-layout oracle _cpsat_bay_timing_verified, where positions are
            # constants).  Encoding it safely would require per-orientation-pair,
            # per-relative-offset reified geometry, which is large and error-prone
            # to get conservative.  Until that is built and verified, leaving this
            # OFF keeps the engine always-feasible.
            pass

        m.Minimize(sum(tard[b] for b in ids))

        # Warm-start hints: gives CP-SAT an immediate feasible incumbent (the
        # current layout) so it only ever polishes -- it cannot report a worse
        # solution than what we already have, and we additionally gate on a
        # strict improvement below.
        for b in ids:
            if b not in mov:
                continue  # frozen blocks are constants, not hintable vars
            m.AddHint(oi[b], hint_o[b])
            m.AddHint(xl[b], hint_xl[b])
            m.AddHint(yl[b], hint_yl[b])
            m.AddHint(entry[b], hint_e[b])

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(max(0.5, bay_budget))
        solver.parameters.num_search_workers = _env_int("OGC_PERBAY_WORKERS", 4)
        solver.parameters.random_seed = 12345  # determinism (A/B stability)
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # No incumbent found within budget; treat as a non-improving noop.
            _rec("noop", new_tard=None,
                 err=f"solver status {solver.StatusName(status)}")
            return None

        new_tard = sum(
            max(0, (int(solver.Value(entry[b])) if b in mov else entry[b])
                + P[b] - D[b])
            for b in ids)
        if new_tard >= cur_bay_tard - 1e-9:
            _rec("noop", new_tard=new_tard)
            return None  # no strict improvement -> reject

        out = {}
        for b in ids:
            if b not in mov:
                out[b] = dict(recs[b])  # frozen -> unchanged record
                continue
            chosen_o = int(solver.Value(oi[b]))
            if chosen_o < 0 or chosen_o >= len(geom[b]):
                chosen_o = hint_o[b]
            _w, _h, offx, offy = geom[b][chosen_o]
            bx_left = int(solver.Value(xl[b]))
            by_bot = int(solver.Value(yl[b]))
            anchor_x = bx_left - offx
            anchor_y = by_bot - offy
            ev = int(solver.Value(entry[b]))
            rec = recs[b]
            out[b] = {
                "block_id": b,
                "bay_id": rec["bay_id"],
                "x": anchor_x,
                "y": anchor_y,
                "orient_idx": chosen_o,
                "entry_time": ev,
                "exit_time": ev + P[b],
            }
        _rec("improved", new_tard=new_tard)
        return out
    except Exception as e:
        if _env_on("OGC_PERBAY_DEBUG", False):
            import traceback
            sys.stderr.write("[perbay] EXCEPTION in _solve_bay():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _rec("error", err=str(e)[:200])
        return None


# -----------------------------------------------------------------------------
# Public contract.
# -----------------------------------------------------------------------------
def improve(prob_info: dict, sol: dict, time_budget: float) -> dict:
    """Polish a feasible solution by jointly re-optimizing block position (x,y),
    orientation, and entry/exit within each bay (bay assignment FIXED, so z2/z3
    are invariant; only per-bay tardiness z1 changes).  Returns an improved
    solution dict if some bay strictly reduced its tardiness, else returns the
    SAME `sol` object (identity) unchanged.  NEVER raises.  Deadline-bounded by
    time_budget seconds from entry (use time.monotonic())."""
    t_enter = time.monotonic()
    deadline = t_enter + float(time_budget)

    # ---- Telemetry (additive, best-effort) ----------------------------------
    # When OGC_PERBAY_LOG names a path, we APPEND exactly one JSON-lines record
    # describing this improve() call.  When unset, _log_path is "" and every
    # telemetry branch is a no-op, leaving behaviour bit-identical to before.
    _log_path = ""
    try:
        _log_path = os.environ.get("OGC_PERBAY_LOG", "").strip()
    except Exception:
        _log_path = ""
    _tel_bays = []          # per-work-bay records (incl. skipped)
    _tel_z1_before = 0.0
    _tel_z1_after = 0.0
    _tel_n_blocks_total = 0
    _tel_n_bays_total = 0
    _tel_n_work_bays = 0
    if _log_path:
        try:
            _tel_n_blocks_total = len(prob_info.get("blocks", {}))
            _tel_n_bays_total = len(prob_info.get("bays", {}))
        except Exception:
            pass

    def _emit_log(fired_flag):
        """Append one JSON line; failure here NEVER affects the return value."""
        if not _log_path:
            return
        try:
            record = {
                "event": "perbay_improve",
                "time_budget": float(time_budget),
                "n_blocks_total": int(_tel_n_blocks_total),
                "n_bays_total": int(_tel_n_bays_total),
                "n_work_bays": int(_tel_n_work_bays),
                "fired": bool(fired_flag),
                "total_wall": float(time.monotonic() - t_enter),
                "z1_before": float(_tel_z1_before),
                "z1_after": float(_tel_z1_after),
                "bays": _tel_bays,
            }
            import json as _json
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(record) + "\n")
                _f.flush()
        except Exception:
            # Telemetry is best-effort; swallow everything.
            if _env_on("OGC_PERBAY_DEBUG", False):
                import traceback
                sys.stderr.write("[perbay] EXCEPTION in _emit_log():\n")
                traceback.print_exc()
                sys.stderr.flush()

    try:
        # Lazy import to avoid a circular import at module load (myalgorithm
        # imports perbay).
        from myalgorithm import _results_from_solution
        from baseline_greedy import _build_operations

        blocks = prob_info["blocks"]
        bays = prob_info["bays"]

        _assign, results, _flat = _results_from_solution(prob_info, sol)

        # Per-bay current tardiness; keep only bays with a recoverable gap.
        work = []  # (bay_idx, ids, cur_tard)
        for j, by_id in results.items():
            if not by_id:
                continue
            ids = list(by_id)
            cur_tard = sum(
                max(0, int(by_id[b]["exit_time"]) - int(blocks[b]["due_date"]))
                for b in ids
            )
            if cur_tard <= 0:
                continue  # cannot reduce z1 below 0 by repositioning
            work.append((j, ids, cur_tard))

        _dbg(f"work bays (cur_tard>0): {len(work)} -> "
             f"{[(j, len(ids), ct) for (j, ids, ct) in work]}")
        # Every cur_tard>0 bay is a "work-bay candidate" for telemetry purposes
        # (n_work_bays counts these, incl. ones later skipped by maxn).
        _tel_n_work_bays = len(work)
        if _log_path:
            _tel_z1_before = float(sum(ct for (_j, _ids, ct) in work))
            _tel_z1_after = _tel_z1_before  # updated as bays improve
        if not work:
            _dbg("no work bays found -> return sol (NOOP)")
            _emit_log(False)
            return sol

        # Biggest payoff first.
        work.sort(key=lambda t: t[2], reverse=True)

        # Default 100: measured per-bay joint solves complete in ~1-2s up to
        # n~90 (warm-started, ~4000 pairwise disjunctions) -- the old default 26
        # silently filtered out EVERY tardy bay on these 60-100-block-per-bay
        # instances (BUG 2: improve() returned instantly, fired=False/wall=0.0s).
        maxn = _env_int("OGC_PERBAY_MAXN", 100)
        bay_cap = _env_float("OGC_PERBAY_BAY_S", 20.0)
        _dbg(f"OGC_PERBAY_MAXN={maxn}  OGC_PERBAY_BAY_S={bay_cap}  "
             f"budget={time_budget:.1f}s")

        # Skip bays that are too large for pairwise CP-SAT.
        kept = [(j, ids, ct) for (j, ids, ct) in work if len(ids) <= maxn]
        for (j, ids, ct) in work:
            if len(ids) > maxn:
                _dbg(f"  bay {j}: SKIP n={len(ids)} > maxn={maxn} (cur_tard={ct})")
                if _log_path:
                    _tel_bays.append({
                        "bay": int(j), "n_blocks": len(ids),
                        "cur_tard": float(ct), "new_tard": None,
                        "wall": 0.0, "status": "skipped_maxn", "err": None,
                    })
        work = kept
        if not work:
            _dbg("all work bays filtered by maxn -> return sol (NOOP)")
            _emit_log(False)
            return sol

        improved_any = False
        # Work on a deep-enough copy only when we actually improve; start by
        # copying per-bay records lazily.
        new_results = None
        remaining_bays = len(work)

        _tel_done_bays = set()  # bay-ids already recorded into _tel_bays
        for (j, ids, cur_tard) in work:
            now = time.monotonic()
            if deadline - now < 1.0:
                _dbg(f"  bay {j}: SKIP deadline ({deadline - now:.2f}s left < 1.0)")
                if _log_path:
                    # Out of budget: this and any remaining kept bays were never
                    # solved.  Record them as no-ops with a budget note so the
                    # bays[] list still covers every considered work bay.
                    for (jj, iids, cct) in work:
                        if jj in _tel_done_bays:
                            continue
                        _tel_bays.append({
                            "bay": int(jj), "n_blocks": len(iids),
                            "cur_tard": float(cct), "new_tard": None,
                            "wall": 0.0, "status": "noop",
                            "err": "deadline reached before solve",
                        })
                break  # not enough time left for a meaningful bay solve
            # Split the remaining budget across the remaining work bays, capped.
            per_bay = (deadline - now) / max(1, remaining_bays)
            per_bay = min(per_bay, bay_cap)
            remaining_bays -= 1
            if per_bay < 0.5:
                _dbg(f"  bay {j}: SKIP per_bay={per_bay:.2f}s < 0.5")
                if _log_path:
                    _tel_bays.append({
                        "bay": int(j), "n_blocks": len(ids),
                        "cur_tard": float(cur_tard), "new_tard": None,
                        "wall": 0.0, "status": "noop",
                        "err": f"per_bay budget {per_bay:.2f}s < 0.5s",
                    })
                    _tel_done_bays.add(j)
                continue

            by_id = results[j]
            W = int(bays[j]["width"]); H = int(bays[j]["height"])
            # Horizon mirrors the fixed-layout oracle: current makespan + maxP.
            cur_makespan = max(int(by_id[b]["exit_time"]) for b in ids)
            max_due = max(int(blocks[b]["due_date"]) for b in ids)
            maxP = max(int(blocks[b]["processing_time"]) for b in ids)
            Hmax = max(cur_makespan, max_due) + maxP

            bay_deadline = now + per_bay
            # "B3 + push" mode (OGC_PERBAY_PUSH, default OFF): only the TARDY
            # blocks are MOVABLE (slide into a crane-clear free spot); the rest
            # are frozen obstacles -> O(|tardy|*n) model, tractable on big bays.
            _movable = None
            if _env_on("OGC_PERBAY_PUSH", False):
                _movable = [b for b in ids
                            if int(by_id[b]["exit_time"]) > int(blocks[b]["due_date"])]
                if not _movable:
                    _movable = None  # nothing tardy here -> full behaviour (no-op anyway)
            _dbg(f"  bay {j}: SOLVE n={len(ids)} cur_tard={cur_tard} "
                 f"per_bay={per_bay:.1f}s W={W} H={H} "
                 f"movable={'all' if _movable is None else len(_movable)}")
            _bay_info = {} if _log_path else None
            _bay_t0 = time.monotonic()
            res = _solve_bay(W, H, ids, by_id, blocks, cur_tard, Hmax,
                             per_bay, bay_deadline, info=_bay_info,
                             movable=_movable)
            _bay_wall = time.monotonic() - _bay_t0
            if res:
                if new_results is None:
                    # Shallow-copy the bay->dict map; deep-copy only mutated bays.
                    new_results = {jj: dict(bb) for jj, bb in results.items()}
                new_results[j] = res
                improved_any = True
                _dbg(f"  bay {j}: IMPROVED")
            else:
                _dbg(f"  bay {j}: no improvement (None)")
            if _log_path:
                _status = (_bay_info or {}).get("status", "noop")
                _new_tard = (_bay_info or {}).get("new_tard", None)
                _err = (_bay_info or {}).get("err", None)
                if _status == "improved" and _new_tard is not None:
                    # Engine-side z1 accounting: swap this bay's cur_tard for the
                    # achieved new_tard (cross-checked against utils in harness).
                    _tel_z1_after += float(_new_tard) - float(cur_tard)
                _tel_bays.append({
                    "bay": int(j), "n_blocks": len(ids),
                    "cur_tard": float(cur_tard),
                    "new_tard": (None if _new_tard is None else float(_new_tard)),
                    "wall": float(_bay_wall), "status": _status, "err": _err,
                })
                _tel_done_bays.add(j)

        if not improved_any:
            _dbg("no bay improved -> return sol (NOOP)")
            _emit_log(False)
            return sol

        new_flat = [dict(a) for by in new_results.values() for a in by.values()]
        _emit_log(True)
        return {"operations": _build_operations(new_flat)}
    except Exception:
        # Never propagate: worst case, the input solution is returned unchanged.
        if _env_on("OGC_PERBAY_DEBUG", False):
            import traceback
            sys.stderr.write("[perbay] EXCEPTION in improve():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _emit_log(False)
        return sol


def algorithm(prob_info: dict, timelimit: float) -> dict:
    """Isolated-testing entry: build a baseline via myalgorithm._legacy_algorithm,
    then polish it with improve().  Minimal and never-raises (fallback: return the
    baseline solution, or whatever we have)."""
    t0 = time.monotonic()
    sol = None
    try:
        import myalgorithm
        sol = myalgorithm._legacy_algorithm(prob_info, timelimit * 0.6)
    except Exception:
        sol = None
    if sol is None:
        # No baseline available -- nothing to polish.  Return an empty-ish but
        # well-formed solution so the caller never crashes.
        return {"operations": {}}
    try:
        remaining = max(0.0, timelimit - (time.monotonic() - t0))
        return improve(prob_info, sol, remaining)
    except Exception:
        return sol
