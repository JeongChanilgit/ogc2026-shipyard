# rasterpack.py
#
# OGC 2026 -- The Grand Shipyard Puzzle
# Per-bay TRUE-POLYGON RASTER bottom-left-fit (BLF) dense re-packing engine.
#
# This is a GATED best-of CANDIDATE, mirroring perbay.improve()'s contract.  A
# separate integration in myalgorithm.py adopts its output ONLY if the official
# `check_feasibility` passes AND the objective strictly improves, all wrapped in
# try/except.  Therefore this engine:
#   * NEVER raises to the caller (everything wrapped in try/except),
#   * is strictly deadline-bounded (time.monotonic()), and
#   * in the worst case returns the input solution UNCHANGED (identity).
#
# WHY raster-BLF (the density lever).  perbay/the legacy floor place blocks with
# bbox / abutment-BL geometry: they reason about axis-aligned bounding BOXES, so
# the empty space inside a polygon's bbox (the "shoulders" of an irregular hull,
# the gaps between concave edges) is wasted -- two blocks whose bboxes overlap are
# pushed apart even when their TRUE polygons interlock.  A competitor packs ~95%;
# our bbox placement tops out ~80%.  This engine rasterizes the TRUE polygon
# footprint to an integer grid and does collision-free bottom-left placement on
# the RASTER, so two blocks may sit so their bboxes overlap as long as their
# polygon cells don't.  Denser packing => more blocks can co-exist in time => a
# tardy block can ENTER earlier (at its release) instead of waiting for a
# footprint to clear => lower z1.  Bay assignment stays fixed, so Z2 (load) and
# Z3 (preference) are provably invariant; only per-bay tardiness Z1 changes, and
# we only touch bays whose current tardiness > 0.
#
# SAFETY MODEL (the non-negotiable invariant).  Each block's raster mask is a
# SUPERSET of its true float polygon footprint: every grid cell the polygon
# touches (even partially) is set, AND the integer cell-box used for the mask is
# floor/ceil-rounded OUTWARD from the float verts (same conservative rounding as
# perbay._orient_geom).  Hence:
#     raster masks don't intersect  ==>  true polygons don't overlap
#     mask fits in [0,W]x[0,H] cells ==>  float footprint fits the bay
# So a raster-feasible layout is TRULY feasible (stages 2/3/4 of the checker).
# The crane j>=k rule for SINGLE-layer blocks reduces to "footprint-overlapping
# blocks cannot be co-present", which raster no-overlap-when-time-overlapping
# enforces directly.  For MULTI-layer blocks we are CONSERVATIVE (see below).
# The caller re-runs check_feasibility regardless; producing genuinely feasible
# layouts is what makes the candidate actually get ADOPTED rather than rejected.
#
# CRANE / MULTI-LAYER handling (v1, documented honestly).
#   * SINGLE-layer block: exact.  Its footprint = its one polygon; the j>=k rule
#     collapses to "no two footprint-overlapping single-layer blocks co-present",
#     which is exactly raster no-overlap over the time-overlap window.
#   * MULTI-layer block: CONSERVATIVE.  Its footprint mask = the UNION of all its
#     layer polygons, and it is treated as fully occupying that footprint for its
#     ENTIRE [entry,exit) interval against EVERY co-present block.  This FORBIDS
#     some legal crane LIFO stacking (where a smaller-footprint block nests on top
#     within a larger one), so it can be SUBOPTIMAL, but it is always FEASIBLE:
#     no co-present pair ever shares a footprint cell, so no j>=k obstruction and
#     no same-layer collision can fire at any layer.  prob_38 is 222/250 multi-
#     layer, so this conservatism is the binding limitation for that instance --
#     see the validation note returned to the caller.
#
# CRANE-SAFE STACKING (v2, env OGC_RP_STACK, default ON).  The conservatism above
# is exactly the lever the competitor exploits and we don't: a shorter block can
# co-exist UNDER/AROUND a taller block's upper layers when the crane j>=k rule
# permits a LIFO nesting (the inner block enters AFTER and exits BEFORE the outer,
# so the crane never has to lift the outer past the inner).  v1 forbids ALL
# footprint overlap; v2 instead, when a raster candidate has a footprint COLLISION
# with co-present blocks, tries to ACCEPT it as a stacked/co-present block and
# VALIDATES the configuration with the REAL crane checker (utils.check_entry /
# check_exit / check_collisions over the co-present sets, exactly as the official
# check_feasibility stages 2/3/5 do).  Because the crane exit feasibility is
# FUTURE-dependent (a later block can box an earlier one in), per-candidate
# incremental checks are NOT sufficient; v2 therefore also runs a FULL-bay crane
# re-validation after the greedy completes, and the whole bay is only adopted if
# it passes (and z1 strictly improves).  Candidate entry/exit are biased toward
# LIFO nesting (entry >= outer.entry, exit <= outer.exit) so the configuration is
# one the checker will accept when the layer geometry allows.  This is correct by
# construction (real checker is the oracle) and bounded (only DELAYED blocks try
# stacking, capped attempts, deadline-respecting), falling back to v1 behaviour
# (forbid overlap, delay) whenever no stacked candidate validates.  A prior
# CP-SAT crane-placement attempt (OGC_CRANE / OGC_PERBAY_CRANE) was FALSIFIED in
# this project; this is a different, validation-driven route, but it is a known-
# hard lever -- the engine reports honestly (debug counters) when it cannot beat
# v1, and the caller's check_feasibility + strict-improve gate is the backstop.
#
# TEMPORAL model.  Re-decode each work bay from scratch in EDD order.  A block's
# placement is (orient, gx, gy, entry); it is valid iff for every ALREADY-placed
# block whose [entry',exit') overlaps [entry,entry+P) the two masks at their grid
# offsets have empty bitwise-AND.  We try entry=release first (zero tardiness);
# if no collision-free bottom-left spot exists at that entry over all orientations
# we advance entry to the next placed-block exit time and retry, until a spot is
# found (the bay is finite + the horizon bounded, so this always terminates with
# a placement).  Earliest feasible entry => minimal tardiness for that block under
# this greedy.

from __future__ import annotations

import math
import os
import sys
import time

try:
    import numpy as _np
except Exception:  # pragma: no cover - numpy is present in ogc2025 env
    _np = None

try:
    from shapely.geometry import Polygon as _ShapelyPolygon
    from shapely.geometry import box as _shapely_box
    _HAVE_SHAPELY = True
except Exception:  # pragma: no cover
    _HAVE_SHAPELY = False


# -----------------------------------------------------------------------------
# Tiny env helpers -- replicated inline (NOT imported from myalgorithm) to avoid
# importing myalgorithm at module load time (circular import: myalgorithm imports
# rasterpack).  Behaviour is bit-identical to perbay._env_* / myalgorithm._env_*.
# All three never raise; an unset/unparseable var returns the default.
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
    """Stderr trace, gated by OGC_RASTERPACK_DEBUG (default off).  Never raises."""
    try:
        if _env_on("OGC_RASTERPACK_DEBUG", False):
            sys.stderr.write("[rasterpack] " + msg + "\n")
            sys.stderr.flush()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Geometry: conservative integer bbox for orientation o (mirrors perbay).
#
# Same anchor convention as utils.Block.__post_init__:
#   layers = shape[o]["layers"]; ref = layers[0][0] (first vertex, first layer);
#   local vertex (vx,vy) -> world (vx + x - ref_x, vy + y - ref_y).
# So the world bbox-min corner is anchor + (min - ref); we FLOOR the min offset
# and CEIL the max extent so the integer box CONTAINS the float polygon:
#   bbox_left  = anchor_x + offminx <= world_min_x   (offminx = floor(min-ref))
#   bbox_right = anchor_x + offminx + w >= world_max_x
# Hence integer non-overlap => float non-overlap, integer in-bounds => float in.
# -----------------------------------------------------------------------------
def _orient_geom(block_data: dict, o: int):
    """Return (w, h, offminx, offminy) as ints for orientation o, outward-rounded
    so the integer bbox conservatively CONTAINS the true float polygon."""
    raw_layers = block_data["shape"][o]["layers"]
    layers = [list(l) for l in raw_layers if l]
    if not layers:
        return 1, 1, 0, 0
    ref_x, ref_y = layers[0][0]
    all_verts = [v for l in layers for v in l]
    min_x = min(v[0] for v in all_verts)
    min_y = min(v[1] for v in all_verts)
    max_x = max(v[0] for v in all_verts)
    max_y = max(v[1] for v in all_verts)
    offminx = int(math.floor(min_x - ref_x))
    offminy = int(math.floor(min_y - ref_y))
    w = int(math.ceil(max_x - ref_x)) - offminx
    h = int(math.ceil(max_y - ref_y)) - offminy
    if w <= 0:
        w = 1
    if h <= 0:
        h = 1
    return w, h, offminx, offminy


# -----------------------------------------------------------------------------
# Rasterization: true-polygon footprint -> bool mask (SUPERSET of the polygon).
#
# The mask is on an integer grid with cell size `grid` (default 1).  Cell (cx,cy)
# spans world [bx + cx*grid, bx + (cx+1)*grid) x [by + cy*grid, by + (cy+1)*grid)
# where (bx,by) = anchor + (offminx,offminy) is the conservative bbox corner.
# A cell is SET if the polygon (union over all layers) touches it AT ALL.  We
# overshoot (set a cell that the polygon merely grazes) which only makes the mask
# bigger => still a superset => still feasibility-safe.  Two passes:
#   (1) shapely: cell is set iff box(cell).intersects(footprint) -- exact touch
#       test, robust to concavity/holes; we additionally OR in a vertex/edge
#       rasterization so degenerate slivers can't slip through.
#   (2) fallback (no shapely): set every cell of the conservative bbox (the mask
#       degenerates to the bbox -- still a superset, just no density gain).
# The mask is (h_cells x w_cells) bool, indexed [row=cy, col=cx].
# -----------------------------------------------------------------------------
def _world_layers(block_data: dict, o: int):
    """Union footprint polygon vertices (all layers) in LOCAL-minus-ref frame, i.e.
    translated so the conservative bbox corner is at grid origin (0,0)."""
    raw_layers = block_data["shape"][o]["layers"]
    layers = [list(l) for l in raw_layers if l]
    if not layers:
        return None, None
    ref_x, ref_y = layers[0][0]
    w, h, offminx, offminy = _orient_geom(block_data, o)
    # Shift verts so (offminx,offminy) maps to (0,0): v' = (v - ref) - (offminx,offminy)
    shifted = []
    for l in layers:
        poly = [((vx - ref_x) - offminx, (vy - ref_y) - offminy) for (vx, vy) in l]
        shifted.append(poly)
    return shifted, (w, h)


def _rasterize(block_data: dict, o: int, grid: int):
    """Return a bool numpy mask (h_cells x w_cells) that is a SUPERSET of the true
    polygon footprint for orientation o, plus (w, h, offminx, offminy).  Never
    raises; on any failure returns a full-bbox mask (still a valid superset)."""
    w, h, offminx, offminy = _orient_geom(block_data, o)
    g = max(1, int(grid))
    w_cells = int(math.ceil(w / g))
    h_cells = int(math.ceil(h / g))
    if w_cells <= 0:
        w_cells = 1
    if h_cells <= 0:
        h_cells = 1
    # Default fallback mask = full bbox (always a superset of the polygon).
    if _np is None:
        return None, (w, h, offminx, offminy)
    mask = _np.ones((h_cells, w_cells), dtype=bool)
    if not _HAVE_SHAPELY:
        return mask, (w, h, offminx, offminy)
    try:
        shifted, _wh = _world_layers(block_data, o)
        if not shifted:
            return mask, (w, h, offminx, offminy)
        polys = []
        for poly in shifted:
            if len(poly) < 3:
                continue
            try:
                p = _ShapelyPolygon(poly)
                if not p.is_valid:
                    p = p.buffer(0)
                if p.is_empty:
                    continue
                polys.append(p)
            except Exception:
                continue
        if not polys:
            return mask, (w, h, offminx, offminy)
        # Union footprint of all layers (conservative for multi-layer).
        foot = polys[0]
        for p in polys[1:]:
            try:
                foot = foot.union(p)
            except Exception:
                pass
        if foot.is_empty:
            return mask, (w, h, offminx, offminy)
        # Start EMPTY, then set every cell the footprint touches (superset).
        mask = _np.zeros((h_cells, w_cells), dtype=bool)
        # Outward-buffer a hair so a polygon edge running exactly along a cell
        # boundary still flags the adjacent cell -- pure superset safety.
        try:
            foot_b = foot.buffer(1e-9)
        except Exception:
            foot_b = foot
        minx, miny, maxx, maxy = foot.bounds
        c0 = max(0, int(math.floor(minx / g)))
        c1 = min(w_cells, int(math.ceil(maxx / g)))
        r0 = max(0, int(math.floor(miny / g)))
        r1 = min(h_cells, int(math.ceil(maxy / g)))
        for cy in range(r0, r1):
            ylo = cy * g
            yhi = (cy + 1) * g
            for cx in range(c0, c1):
                xlo = cx * g
                xhi = (cx + 1) * g
                try:
                    cell = _shapely_box(xlo, ylo, xhi, yhi)
                    if foot_b.intersects(cell):
                        mask[cy, cx] = True
                except Exception:
                    mask[cy, cx] = True  # err on the safe (occupied) side
        if not mask.any():
            # Degenerate: keep full bbox rather than an empty mask.
            mask = _np.ones((h_cells, w_cells), dtype=bool)
        return mask, (w, h, offminx, offminy)
    except Exception:
        return _np.ones((h_cells, w_cells), dtype=bool), (w, h, offminx, offminy)


# -----------------------------------------------------------------------------
# Crane-safe stacking validation (v2) via the REAL checker.
#
# The official check_feasibility validates the crane j>=k rule by calling
# utils.check_entry / check_exit / check_collisions over the co-present sets at
# each event time (stages 2/3/5).  We replay exactly that semantics on the bay's
# placements so a "stacked" (footprint-overlapping but crane-LIFO-legal)
# configuration is accepted iff the official checker would accept it.  Real
# Shapely calls => slow; callers bound how often this is invoked.
# -----------------------------------------------------------------------------
def _make_block(blocks, b, anchor_x, anchor_y, orient_idx):
    """Build a utils.Block at an integer anchor/orientation.  Returns None on any
    failure (caller treats that as 'cannot validate' -> reject candidate)."""
    try:
        from utils import Block as _Block
        return _Block(block_id=b, block_data=blocks[b],
                      x=int(anchor_x), y=int(anchor_y), orient_idx=int(orient_idx))
    except Exception:
        return None


def _bay_crane_feasible(bay_obj, placements):
    """Replay check_feasibility stages 2/3/4 over a set of bay placements using
    the REAL checker.  `placements` = list of (block_id, Block_obj, entry, exit).
    Returns True iff every ENTRY, EXIT, and time-overlap collision is crane/
    collision feasible -- i.e. exactly what the official checker tests for this
    single bay.  Never raises (returns False on any error => conservative)."""
    try:
        from utils import check_entry as _ce, check_exit as _cx, \
            check_collisions as _cc
    except Exception:
        return False
    try:
        n = len(placements)
        # Stage 2: every ENTRY feasible vs the set present strictly during it.
        for i in range(n):
            bi, obj_i, ei, xi = placements[i]
            present = []
            for k in range(n):
                if k == i:
                    continue
                bk, obj_k, ek, xk = placements[k]
                # present at instant ei: entry_k <= ei < exit_k
                if ek <= ei < xk:
                    present.append(obj_k)
            if present and _ce(bay_obj, present, obj_i, fast=True):
                return False
        # Stage 3: every EXIT feasible vs the set strictly spanning it.
        for i in range(n):
            bi, obj_i, ei, xi = placements[i]
            present = [obj_i]
            for k in range(n):
                if k == i:
                    continue
                bk, obj_k, ek, xk = placements[k]
                # strictly spanning xi: entry_k < xi < exit_k
                if ek < xi < xk:
                    present.append(obj_k)
            if len(present) > 1 and _cx(bay_obj, present, obj_i, fast=True):
                return False
        # Stage 4: same-height collisions for every time-overlapping pair.
        for i in range(n):
            bi, obj_i, ei, xi = placements[i]
            for k in range(i + 1, n):
                bk, obj_k, ek, xk = placements[k]
                if ei < xk and ek < xi:  # half-open time overlap
                    if _cc(bay_obj, [obj_i, obj_k]):
                        return False
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Per-bay raster-BLF re-decode.
# -----------------------------------------------------------------------------
def _solve_bay(W, H, ids, recs, blocks, cur_bay_tard, grid, bay_deadline,
               info=None, bay_obj=None, stack_counter=None):
    """Re-decode one bay's blocks via true-polygon raster bottom-left-fit to
    minimize this bay's total tardiness.  Bay assignment fixed.

    Returns a dict {block_id: record} for the WHOLE bay if a strictly lower bay
    tardiness was found, else None.  Never raises (returns None on error).

    `info` (optional, telemetry-only): mirrors perbay -- keys "status" (one of
    "improved"/"noop"/"skipped_oob"/"error"), "new_tard" (int|None), "err"
    (str|None).  Best-effort; never affects the return value."""
    def _rec(status, new_tard=None, err=None):
        try:
            if info is not None:
                info["status"] = status
                info["new_tard"] = new_tard
                info["err"] = err
        except Exception:
            pass

    if _np is None:
        _rec("error", err="numpy unavailable")
        return None
    try:
        g = max(1, int(grid))
        Wc = int(math.ceil(W / g))
        Hc = int(math.ceil(H / g))
        if Wc <= 0 or Hc <= 0:
            _rec("error", err=f"degenerate bay grid {Wc}x{Hc}")
            return None

        # ---- Per-block precompute: masks per orientation + EDD key ----------
        masks = {}      # b -> list over o of (mask, w, h, offminx, offminy)
        P = {}; R = {}; D = {}
        for b in ids:
            blk = blocks[b]
            P[b] = int(blk["processing_time"])
            R[b] = int(blk["release_time"])
            D[b] = int(blk["due_date"])
            O_b = len(blk["shape"])
            ml = []
            for o in range(O_b):
                mask, (w, h, offx, offy) = _rasterize(blk, o, g)
                if mask is None:
                    _rec("error", err=f"rasterize block {b} orient {o} failed")
                    return None
                ml.append((mask, w, h, offx, offy))
            masks[b] = ml

        # ---- Horizon: bound entry walk so it always terminates ---------------
        cur_makespan = max(int(recs[b]["exit_time"]) for b in ids)
        max_due = max(D[b] for b in ids)
        maxP = max(P[b] for b in ids)
        Hmax = max(cur_makespan, max_due) + maxP + 1

        # ---- EDD order: due asc, release asc, id asc (deterministic) ---------
        order = sorted(ids, key=lambda b: (D[b], R[b], b))

        # ---- v2 stacking knobs ----------------------------------------------
        stack_on = _env_on("OGC_RP_STACK", True)
        stack_tries = _env_int("OGC_RP_STACK_TRIES", 20)
        # When the greedy re-decode cannot place a block (congested bay), instead
        # of ABORTING the whole bay (v1: revert everything), fall back to the
        # block's ORIGINAL box position/timing so the bay still completes and the
        # gains on the blocks we COULD re-place (incl. stacked ones) are kept.
        # Default ON in v2; the final full-bay crane re-validation + caller's
        # check_feasibility are the backstop.
        keep_orig = _env_on("OGC_RP_KEEP_ORIG", True)

        # placed: list of (b, mask, gx, gy, entry, exit, w_cells, h_cells, o,
        #                  anchor_x, anchor_y).  o/anchor_* let us rebuild the
        #                  utils.Block for the real crane checker (stacking).
        placed = []

        def _blocked_grid(entry, exit_t):
            """Build (once per entry) the Hc x Wc bool occupancy grid = OR of every
            placed block's mask (at its grid offset) whose time interval overlaps
            [entry,exit_t).  The BL scan then tests the candidate against this ONE
            grid instead of looping over all placed blocks per cell -- the speed
            lever for big bays (was O(cells*placed), now O(cells) per entry)."""
            grid_b = _np.zeros((Hc, Wc), dtype=bool)
            for p in placed:
                pmask, pgx, pgy, pe, px, pw, ph = p[1], p[2], p[3], p[4], p[5], p[6], p[7]
                if exit_t <= pe or entry >= px:
                    continue  # time-disjoint
                y0 = pgy; y1 = pgy + ph
                x0 = pgx; x1 = pgx + pw
                if y0 < 0: y0 = 0
                if x0 < 0: x0 = 0
                if y1 > Hc: y1 = Hc
                if x1 > Wc: x1 = Wc
                if y0 >= y1 or x0 >= x1:
                    continue
                sub = pmask[y0 - pgy: y1 - pgy, x0 - pgx: x1 - pgx]
                grid_b[y0:y1, x0:x1] |= sub
            return grid_b

        def _bl_fit(grid_b, ml):
            """Bottom-left fit of any orientation's mask into the FREE space of the
            blocked grid.  Returns (o, gx, gy) of the first (BL) free spot, else
            None.  Vectorized per-orientation: for each candidate top-left (gy,gx)
            the test is a single `(mask & grid_b[...]).any()` over the footprint
            sub-window -- no inner placed loop."""
            for gy in range(0, Hc):
                for gx in range(0, Wc):
                    for o in range(len(ml)):
                        mask, w, h, offx, offy = ml[o]
                        mh, mw = mask.shape
                        if gx + mw > Wc or gy + mh > Hc:
                            continue
                        sub = grid_b[gy:gy + mh, gx:gx + mw]
                        if not (mask & sub).any():
                            return (o, gx, gy)
            return None

        def _collides(mask, gx, gy, entry, exit_t):
            """True if `mask` at grid (gx,gy) over [entry,exit_t) hits any placed
            block whose time interval overlaps.  Pure raster bitwise-AND.  (Kept
            for the stacking branch, which scans only collision cells.)"""
            mh, mw = mask.shape
            for p in placed:
                pmask, pgx, pgy, pe, px, pw, ph = p[1], p[2], p[3], p[4], p[5], p[6], p[7]
                # time-disjoint => no constraint
                if exit_t <= pe or entry >= px:
                    continue
                # bbox overlap in cells?
                ox0 = max(gx, pgx)
                oy0 = max(gy, pgy)
                ox1 = min(gx + mw, pgx + pw)
                oy1 = min(gy + mh, pgy + ph)
                if ox0 >= ox1 or oy0 >= oy1:
                    continue  # cell-bboxes disjoint -> masks can't intersect
                sub_a = mask[oy0 - gy: oy1 - gy, ox0 - gx: ox1 - gx]
                sub_b = pmask[oy0 - pgy: oy1 - pgy, ox0 - pgx: ox1 - pgx]
                if _np.logical_and(sub_a, sub_b).any():
                    return True
            return False

        def _overlap_intervals(gx, gy, mw, mh, mask):
            """Return placed blocks whose raster footprint OVERLAPS this candidate
            footprint (regardless of time), as a list of (entry,exit).  Used to
            bias a stacked candidate's [entry,exit) into a LIFO nest."""
            outl = []
            for p in placed:
                pmask, pgx, pgy, pe, px, pw, ph = p[1], p[2], p[3], p[4], p[5], p[6], p[7]
                ox0 = max(gx, pgx); oy0 = max(gy, pgy)
                ox1 = min(gx + mw, pgx + pw); oy1 = min(gy + mh, pgy + ph)
                if ox0 >= ox1 or oy0 >= oy1:
                    continue
                sub_a = mask[oy0 - gy: oy1 - gy, ox0 - gx: ox1 - gx]
                sub_b = pmask[oy0 - pgy: oy1 - pgy, ox0 - pgx: ox1 - pgx]
                if _np.logical_and(sub_a, sub_b).any():
                    outl.append((pe, px))
            return outl

        def _try_stack(b, o, gx, gy, entry):
            """v2: try to place block b at (o,gx,gy,entry) as a STACKED/co-present
            block, biasing [entry,exit) toward a LIFO nest inside footprint-
            overlapping placed blocks, and VALIDATE with the REAL crane checker.
            Returns (entry_used, exit_used) if the WHOLE bay (placed + candidate)
            stays crane-feasible, else None.  bay_obj must be available."""
            if bay_obj is None:
                return None
            mask, w, h, offx, offy = masks[b][o]
            mh2, mw2 = mask.shape
            ax = gx * g - offx
            ay = gy * g - offy
            cand_obj = _make_block(blocks, b, ax, ay, o)
            if cand_obj is None:
                return None
            # LIFO bias: nest inside the overlapping placed blocks' intervals so
            # the new (inner) block enters after and exits before the outer ones.
            ov = _overlap_intervals(gx, gy, mw2, mh2, mask)
            entries_to_try = [entry]
            if ov:
                lo = max(pe for (pe, px) in ov)   # latest overlapped entry
                if lo > entry:
                    entries_to_try.append(lo)
            for et in entries_to_try:
                if et < R[b]:
                    et = R[b]
                xt = et + P[b]
                # Build the full placement set (existing placed + candidate).
                pls = []
                ok_build = True
                for p in placed:
                    pb2, _m, _gx, _gy, pe2, px2, _w2, _h2, po2, pax2, pay2 = p
                    pobj = _make_block(blocks, pb2, pax2, pay2, po2)
                    if pobj is None:
                        ok_build = False
                        break
                    pls.append((pb2, pobj, pe2, px2))
                if not ok_build:
                    return None
                pls.append((b, cand_obj, et, xt))
                if _bay_crane_feasible(bay_obj, pls):
                    try:
                        if stack_counter is not None:
                            stack_counter[0] += 1
                    except Exception:
                        pass
                    return (et, xt)
            return None

        def _candidate_entries(b):
            """Entry times to try, ascending: release first (zero tardiness),
            then every placed-block exit at/after release (when a footprint may
            clear), capped at the horizon."""
            base = R[b]
            cand = {base}
            for p in placed:
                px = p[5]
                if px >= base:
                    cand.add(px)
            cand = sorted(t for t in cand if t <= Hmax)
            if not cand:
                cand = [base]
            return cand

        time_up = False
        n_stack_attempts = 0   # diagnostics: total _try_stack calls this bay
        n_stack_accepts = 0    # diagnostics: candidates the checker validated
        n_stack_opps = 0       # diagnostics: blocks with no free spot at release
        for b in order:
            if time.monotonic() >= bay_deadline:
                time_up = True
                break
            ml = masks[b]
            best = None  # (entry, o, gx, gy, exit_t)
            cents = _candidate_entries(b)
            for ei, entry in enumerate(cents):
                if time.monotonic() >= bay_deadline:
                    time_up = True
                    break
                exit_t = entry + P[b]
                # Bottom-left scan against the precomputed time-overlap occupancy
                # grid (one build per entry; vectorized per-cell test).  First
                # collision-free spot wins (BL).
                grid_b = _blocked_grid(entry, exit_t)
                fit = _bl_fit(grid_b, ml)
                if fit is not None:
                    o, gx, gy = fit
                    best = (entry, o, gx, gy, exit_t)
                    break  # earliest entry with a non-overlap spot => min tard
                # ---- v2 crane-safe stacking attempt -------------------------
                # Only at the FIRST (earliest, = release) candidate entry, and
                # only when this block would otherwise be DELAYED (entry>release
                # has no spot => it's tardy-bound).  Footprint-overlapping but
                # crane-LIFO-legal co-presence can let it enter NOW instead.
                if (stack_on and bay_obj is not None and ei == 0
                        and stack_tries > 0):
                    n_stack_opps += 1
                    tries = 0
                    sfound = None
                    # grid_b (already built for this entry) marks time-overlap
                    # occupancy.  We want candidate spots that DO collide (v1
                    # rejects them) but might be crane-LIFO-legal -> bottom-left
                    # scan, picking the spot with the LEAST footprint overlap
                    # first (most likely to nest), capped at stack_tries.
                    for gy in range(0, Hc):
                        if sfound or tries >= stack_tries:
                            break
                        if time.monotonic() >= bay_deadline:
                            time_up = True
                            break
                        for gx in range(0, Wc):
                            if tries >= stack_tries:
                                break
                            for o in range(len(ml)):
                                mask, w, h, offx, offy = ml[o]
                                mh, mw = mask.shape
                                if gx + mw > Wc or gy + mh > Hc:
                                    continue
                                sub = grid_b[gy:gy + mh, gx:gx + mw]
                                # Stacking only matters where v1 collides.
                                if not (mask & sub).any():
                                    continue
                                tries += 1
                                n_stack_attempts += 1
                                st = _try_stack(b, o, gx, gy, entry)
                                if st is not None:
                                    n_stack_accepts += 1
                                    et, xt = st
                                    sfound = (et, o, gx, gy, xt)
                                    break
                                if tries >= stack_tries:
                                    break
                            if sfound or tries >= stack_tries:
                                break
                    if sfound is not None:
                        best = sfound
                        break  # stacked entry at/near release => minimal tard
            if best is None:
                if not keep_orig:
                    # v1 behaviour: cannot build a complete feasible bay -> revert.
                    _dbg(f"    bay diag(ABORT): placed={len(placed)}/{len(order)} "
                         f"failed_block={b} stack_attempts={n_stack_attempts} "
                         f"stack_accepts={n_stack_accepts}")
                    _rec("noop", err=f"no placement for block {b}")
                    return None
                # v2 keep-original: re-place this block at its ORIGINAL box
                # pos/orient/entry so the bay still completes; the FINAL full-bay
                # crane re-validation (and the caller's check_feasibility) gate
                # the whole bay, so an infeasible combination is rejected safely.
                rec = recs[b]
                o0 = int(rec["orient_idx"])
                if o0 < 0 or o0 >= len(ml):
                    o0 = 0
                mask, w, h, offx, offy = ml[o0]
                mh, mw = mask.shape
                e0 = int(rec["entry_time"])
                x0 = int(rec["exit_time"])
                ax0 = int(rec["x"]); ay0 = int(rec["y"])
                # grid cell of the original bbox corner: bbox_left = anchor + off
                gx0 = (ax0 + offx) // g
                gy0 = (ay0 + offy) // g
                placed.append((b, mask, gx0, gy0, e0, x0, mw, mh,
                               o0, ax0, ay0))
                continue
            entry, o, gx, gy, exit_t = best
            mask, w, h, offx, offy = ml[o]
            mh, mw = mask.shape
            anchor_x = gx * g - offx
            anchor_y = gy * g - offy
            placed.append((b, mask, gx, gy, entry, exit_t, mw, mh,
                           o, anchor_x, anchor_y))

        _dbg(f"    bay diag: placed={len(placed)}/{len(order)} "
             f"time_up={time_up} stack_opps={n_stack_opps} "
             f"stack_attempts={n_stack_attempts} stack_accepts={n_stack_accepts}")
        if time_up and len(placed) < len(order):
            _rec("noop", err="deadline before all blocks placed")
            return None

        # ---- Evaluate new bay tardiness -------------------------------------
        new_tard = sum(max(0, p[5] - D[p[0]]) for p in placed)
        if new_tard >= cur_bay_tard - 1e-9:
            _rec("noop", new_tard=int(new_tard))
            return None  # no strict improvement -> reject

        # ---- Final FULL-bay crane re-validation (v2, future-dependent) ------
        # Per-candidate stacking checks are necessary but not globally sufficient
        # (a later block can box an earlier one in).  When ANY stacking was used
        # (or always, cheaply, when stacking is on), re-validate the whole bay
        # with the REAL checker; if it fails, reject this bay (keep original).
        # The caller's check_feasibility is the ultimate backstop, but rejecting
        # here avoids handing up a bay that would be discarded anyway.
        if stack_on and bay_obj is not None:
            pls = []
            ok_build = True
            for p in placed:
                pb2, _m, _gx, _gy, pe2, px2, _w2, _h2, po2, pax2, pay2 = p
                pobj = _make_block(blocks, pb2, pax2, pay2, po2)
                if pobj is None:
                    ok_build = False
                    break
                pls.append((pb2, pobj, pe2, px2))
            if (not ok_build) or (not _bay_crane_feasible(bay_obj, pls)):
                _rec("noop", err="final bay crane re-validation failed")
                return None

        # ---- Build records (grid cell -> anchor) ----------------------------
        # cell (gx,gy) bbox corner = (gx*g, gy*g) relative to (offminx,offminy)
        # added to anchor.  bbox_left = anchor_x + offminx  =>  with the mask
        # placed at grid (gx,gy), bbox_left = gx*g (bay coords), so:
        #   anchor_x = gx*g - offminx ;  anchor_y = gy*g - offminy
        out = {}
        for p in placed:
            b, mask, gx, gy, entry, exit_t, mw, mh, chosen_o, anchor_x, anchor_y = p
            rec = recs[b]
            out[b] = {
                "block_id": b,
                "bay_id": rec["bay_id"],
                "x": int(anchor_x),
                "y": int(anchor_y),
                "orient_idx": int(chosen_o),
                "entry_time": int(entry),
                "exit_time": int(exit_t),
            }
        _rec("improved", new_tard=int(new_tard))
        return out
    except Exception as e:
        if _env_on("OGC_RASTERPACK_DEBUG", False):
            import traceback
            sys.stderr.write("[rasterpack] EXCEPTION in _solve_bay():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _rec("error", err=str(e)[:200])
        return None


# -----------------------------------------------------------------------------
# Public contract (mirrors perbay.improve()).
# -----------------------------------------------------------------------------
def improve(prob_info: dict, sol: dict, time_budget: float) -> dict:
    """Polish a feasible solution by raster bottom-left-fit re-decoding each bay
    (bay assignment FIXED, so z2/z3 are invariant; only per-bay tardiness z1
    changes).  Returns an improved solution dict if some bay strictly reduced its
    tardiness, else returns the SAME `sol` object (identity) unchanged.  NEVER
    raises.  Deadline-bounded by time_budget seconds from entry."""
    t_enter = time.monotonic()
    deadline = t_enter + float(time_budget)

    # ---- Telemetry (additive, best-effort; same schema as perbay) -----------
    _log_path = ""
    try:
        _log_path = os.environ.get("OGC_PERBAY_LOG", "").strip()
    except Exception:
        _log_path = ""
    _tel_bays = []
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
        if not _log_path:
            return
        try:
            record = {
                "event": "rasterpack_improve",
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
            if _env_on("OGC_RASTERPACK_DEBUG", False):
                import traceback
                sys.stderr.write("[rasterpack] EXCEPTION in _emit_log():\n")
                traceback.print_exc()
                sys.stderr.flush()

    try:
        if _np is None:
            _dbg("numpy unavailable -> return sol (NOOP)")
            _emit_log(False)
            return sol

        # Lazy import to avoid a circular import at module load.
        from myalgorithm import _results_from_solution
        from baseline_greedy import _build_operations
        try:
            from utils import Bay as _Bay
        except Exception:
            _Bay = None

        blocks = prob_info["blocks"]
        bays = prob_info["bays"]

        # v2 stacking instrumentation: count of crane-validated stacked placements
        # accepted across the whole improve() call (reported via debug + telemetry).
        _stack_counter = [0]

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
                continue  # cannot reduce z1 below 0 by re-packing
            work.append((j, ids, cur_tard))

        _dbg(f"work bays (cur_tard>0): {len(work)} -> "
             f"{[(j, len(ids), ct) for (j, ids, ct) in work]}")
        _tel_n_work_bays = len(work)
        if _log_path:
            _tel_z1_before = float(sum(ct for (_j, _ids, ct) in work))
            _tel_z1_after = _tel_z1_before
        if not work:
            _dbg("no work bays found -> return sol (NOOP)")
            _emit_log(False)
            return sol

        # Biggest payoff first.
        work.sort(key=lambda t: t[2], reverse=True)

        maxn = _env_int("OGC_RP_MAXN", 200)
        bay_cap = _env_float("OGC_RP_BAY_S", 30.0)
        grid = _env_int("OGC_RP_GRID", 1)
        _dbg(f"OGC_RP_MAXN={maxn}  OGC_RP_BAY_S={bay_cap}  OGC_RP_GRID={grid}  "
             f"budget={time_budget:.1f}s")

        # Skip bays too large for the BL scan.
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
        new_results = None
        remaining_bays = len(work)

        _tel_done_bays = set()
        for (j, ids, cur_tard) in work:
            now = time.monotonic()
            if deadline - now < 1.0:
                _dbg(f"  bay {j}: SKIP deadline ({deadline - now:.2f}s left < 1.0)")
                if _log_path:
                    for (jj, iids, cct) in work:
                        if jj in _tel_done_bays:
                            continue
                        _tel_bays.append({
                            "bay": int(jj), "n_blocks": len(iids),
                            "cur_tard": float(cct), "new_tard": None,
                            "wall": 0.0, "status": "noop",
                            "err": "deadline reached before solve",
                        })
                break
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
            bay_deadline = now + per_bay
            # Build a real utils.Bay for the crane-checker (v2 stacking).  If the
            # constructor fails for any reason, bay_obj=None disables stacking for
            # this bay (engine falls back to v1 no-overlap behaviour).
            bay_obj = None
            if _Bay is not None:
                try:
                    bay_obj = _Bay.from_dict(bays[j], j)
                except Exception:
                    try:
                        bay_obj = _Bay(width=W, height=H, id=j)
                    except Exception:
                        bay_obj = None
            _dbg(f"  bay {j}: SOLVE n={len(ids)} cur_tard={cur_tard} "
                 f"per_bay={per_bay:.1f}s W={W} H={H}")
            _bay_info = {} if _log_path else None
            _bay_t0 = time.monotonic()
            res = _solve_bay(W, H, ids, by_id, blocks, cur_tard, grid,
                             bay_deadline, info=_bay_info,
                             bay_obj=bay_obj, stack_counter=_stack_counter)
            _bay_wall = time.monotonic() - _bay_t0
            if res:
                if new_results is None:
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
                    _tel_z1_after += float(_new_tard) - float(cur_tard)
                _tel_bays.append({
                    "bay": int(j), "n_blocks": len(ids),
                    "cur_tard": float(cur_tard),
                    "new_tard": (None if _new_tard is None else float(_new_tard)),
                    "wall": float(_bay_wall), "status": _status, "err": _err,
                })
                _tel_done_bays.add(j)

        _dbg(f"stacked placements accepted (crane-validated): {_stack_counter[0]}")
        if not improved_any:
            _dbg("no bay improved -> return sol (NOOP)")
            _emit_log(False)
            return sol

        new_flat = [dict(a) for by in new_results.values() for a in by.values()]
        _emit_log(True)
        return {"operations": _build_operations(new_flat)}
    except Exception:
        if _env_on("OGC_RASTERPACK_DEBUG", False):
            import traceback
            sys.stderr.write("[rasterpack] EXCEPTION in improve():\n")
            traceback.print_exc()
            sys.stderr.flush()
        _emit_log(False)
        return sol


def algorithm(prob_info: dict, timelimit: float) -> dict:
    """Isolated-testing entry: build a baseline via myalgorithm._legacy_algorithm,
    then polish it with improve().  Minimal and never-raises (fallback: return the
    baseline solution, or an empty-ish well-formed solution)."""
    t0 = time.monotonic()
    sol = None
    try:
        import myalgorithm
        sol = myalgorithm._legacy_algorithm(prob_info, timelimit * 0.6)
    except Exception:
        sol = None
    if sol is None:
        return {"operations": {}}
    try:
        remaining = max(0.0, timelimit - (time.monotonic() - t0))
        return improve(prob_info, sol, remaining)
    except Exception:
        return sol
