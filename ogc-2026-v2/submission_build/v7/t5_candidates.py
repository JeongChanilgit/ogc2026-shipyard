"""T5-1: raster column-drop packing candidate generator (OGC_T5_CANDS, default OFF).

WHY: collision/crane checks are polygon-exact (Shapely), but every candidate
GENERATOR in the solver proposes only bbox-corner positions (_candidate_positions
pairs placed right-edge x with placed top-edge y; _candidate_positions_fast keeps
the column-supported subset).  Two non-convex polygons can interlock far tighter
than their bounding boxes allow, yet no generator ever PROPOSES such a position,
so the exact checks never get a chance to accept one -- the bbox->polygon gap
stays unused and dense bays serialise/spill more than necessary.

This module proposes EXTRA (x, y) reference positions from the polygon rasters
baseline_greedy already computes for the raster floor (OGC_FLOOR_RASTER):

    for each integer reference-x where the block fits, drop the block's
    per-column BOTTOM cell profile onto the per-column TOP cell profile
    (skyline) of the placed blocks -> the lowest y where the rasters stack.

Cell convention matches baseline_greedy._rasterize_layer_cells: a cell (ix, iy)
is the unit square [ix, ix+1) x [iy, iy+1), and a block's raster is a
CONSERVATIVE SUPERSET of its polygons.  Consequences, both acceptable here:

  * a proposal can land ~1 cell HIGHER than the polygon-tight optimum (the
    superset inflates both profiles by up to one cell) -- still far tighter
    than bbox stacking for interlocking shapes;
  * the skyline drop knows nothing about time overlap or the crane j>=k rule.

Candidates are PROPOSALS ONLY: every consumer runs them through the existing
polygon-exact placement pipeline (bay.contains_block + crane-safe slot search),
which rejects anything unsound.  This generator only widens the proposal set.

All public functions are exception-proof (they return [] / the base list on any
internal error) and the whole feature is gated by OGC_T5_CANDS (default OFF).
"""

from __future__ import annotations

import math
import os

try:  # numpy exists on the evaluation server; the pure-python fallback below
    import numpy as _np  # keeps the module importable (and functional) without it
except Exception:  # pragma: no cover
    _np = None

try:
    from utils import Block as _Block
except Exception:  # pragma: no cover - utils is always importable in this repo
    _Block = None


# -----------------------------------------------------------------------------
# Gating / knobs
# -----------------------------------------------------------------------------

def t5_enabled() -> bool:
    """True when OGC_T5_CANDS (default OFF) turns the raster column-drop merge ON
    at the integration sites.  Read per call (same idiom as
    baseline_greedy._raster_floor_on) so a tester can flip it between runs."""
    try:
        return os.environ.get("OGC_T5_CANDS", "").strip().lower() in (
            "1", "true", "on", "yes")
    except Exception:
        return False


def _default_max_k() -> int:
    """Candidate cap when the adapter caller does not pass one.  OGC_T5_CANDS_K
    (default 40) so experiments can widen/narrow without a code edit."""
    try:
        return max(1, int(os.environ.get("OGC_T5_CANDS_K", "40") or "40"))
    except Exception:
        return 40


# -----------------------------------------------------------------------------
# Core skyline drop on raster cell sets
# -----------------------------------------------------------------------------

def column_drop_candidates(bay_w, bay_h, placed_cells, block_cells_at_origin,
                           max_k=40, stride=1):
    """Skyline column-drop candidate positions from raster cell sets.

    placed_cells: cell set (set/frozenset of (ix, iy), WORLD coords) of the
    blocks the caller considers occupying -- typically the union of
    _block_raster_cells over the placed (time-overlapping) blocks.
    block_cells_at_origin: the candidate block rasterised at reference position
    (0, 0).  The reference point is the first vertex of the first layer, which
    the instance generator guarantees to be (0, 0) in local coordinates, so an
    INTEGER shift (x, y) maps these cells exactly to (ix + x, iy + y).

    For every integer reference-x where the block's cell span fits the bay
    (stride > 1 subsamples the x range), compute the lowest landing

        y(x) = max over local columns c of (top[x + c] - bot[c])

    where top[col] = max(iy) + 1 over placed cells in that column (0 if empty)
    and bot[c] = min(iy) over the block's cells in local column c (columns the
    block does not touch impose no constraint).  Because rasters are SUPERSETS
    of the polygons, a candidate may sit up to ~1 cell higher than the
    polygon-tight position -- accepted by design; the polygon-exact checks
    downstream own correctness.

    Returns [(x, y), ...] sorted by ascending y then x (lowest landings first),
    capped at max_k (<=0 means no cap).  Returns [] when the block cannot fit
    the bay at any position, and on ANY internal error (never raises).
    """
    try:
        return _column_drop_impl(float(bay_w), float(bay_h),
                                 placed_cells, block_cells_at_origin,
                                 int(max_k), max(1, int(stride)))
    except Exception:
        return []


def _column_drop_impl(bay_w, bay_h, placed_cells, block_cells, max_k, stride):
    if not block_cells:
        return []
    # Bay size in whole unit cells.  ceil is PERMISSIVE on fractional bay dims
    # (a boundary cell may poke out by <1 unit) -- downstream bay.contains_block
    # is polygon-exact and rejects any over-reach.  OGC bays have integral dims,
    # so in practice this is exact.
    W = int(math.ceil(bay_w - 1e-9))
    H = int(math.ceil(bay_h - 1e-9))
    if W <= 0 or H <= 0:
        return []
    bx0 = min(c[0] for c in block_cells)
    bx1 = max(c[0] for c in block_cells)
    by0 = min(c[1] for c in block_cells)
    by1 = max(c[1] for c in block_cells)
    wc = bx1 - bx0 + 1                    # block cell-span width
    if wc > W or (by1 - by0 + 1) > H:
        return []                         # raster cannot fit the bay at all
    x_lo, x_hi = -bx0, W - 1 - bx1        # ref-x range keeping all columns in-bay
    y_cap = H - 1 - by1                   # max ref-y keeping the top row in-bay
    if x_hi < x_lo:
        return []
    _NOBLK = 1 << 30                      # sentinel: block has no cell in column

    out = []
    if _np is not None:
        top = _np.zeros(W, dtype=_np.int64)
        if placed_cells:
            pc = _np.array(list(placed_cells), dtype=_np.int64)
            if pc.ndim == 2 and pc.shape[1] == 2:
                m = (pc[:, 0] >= 0) & (pc[:, 0] < W)
                if m.any():
                    _np.maximum.at(top, pc[m, 0], pc[m, 1] + 1)
        bot = _np.full(wc, _NOBLK, dtype=_np.int64)
        bc = _np.array(list(block_cells), dtype=_np.int64)
        _np.minimum.at(bot, bc[:, 0] - bx0, bc[:, 1])
        for x in range(x_lo, x_hi + 1, stride):
            c0 = x + bx0                  # leftmost WORLD column of the block
            # Columns the block does not touch carry bot=_NOBLK -> a hugely
            # negative term, never the max.  top >= 0 guarantees y >= -by0
            # (the bottom cell row never sinks below the bay floor).
            y = int((top[c0:c0 + wc] - bot).max())
            if y <= y_cap:
                out.append((x, y))
    else:
        # Pure-python fallback (no numpy): identical profiles via plain lists.
        top = [0] * W
        for (ix, iy) in placed_cells or ():
            if 0 <= ix < W and iy + 1 > top[ix]:
                top[ix] = iy + 1
        bot = [_NOBLK] * wc
        for (ix, iy) in block_cells:
            c = ix - bx0
            if iy < bot[c]:
                bot[c] = iy
        spans = [c for c in range(wc) if bot[c] != _NOBLK]
        for x in range(x_lo, x_hi + 1, stride):
            c0 = x + bx0
            y = max(top[c0 + c] - bot[c] for c in spans)
            if y <= y_cap:
                out.append((x, y))
    out.sort(key=lambda xy: (xy[1], xy[0]))  # lowest landings first
    if max_k > 0 and len(out) > max_k:
        out = out[:max_k]
    return out


# -----------------------------------------------------------------------------
# Adapter from the solver's placed-Block representation
# -----------------------------------------------------------------------------

# baseline_greedy is imported LAZILY (memoised on success) to avoid an import
# cycle: baseline_greedy's gated phase-1 merge imports this module, and this
# module wants baseline_greedy._block_raster_cells (the per-Block cached
# edge+scanline rasteriser).  On import failure each call falls back to the
# coarse bbox-fill raster below and retries the real import next time.
_RASTER_FN = [None]


def _fallback_block_cells(block) -> frozenset:
    """bbox-fill raster used only when baseline_greedy is unavailable: for each
    layer polygon, add the full outward-rounded bbox rectangle of cells.  A much
    coarser SUPERSET than baseline's edge+scanline raster (no interlocking
    inside a layer bbox), but keeps the generator functional and safe."""
    cells = set()
    try:
        layers = block.layers_at_pos()
    except Exception:
        return frozenset()
    for verts in layers:
        if not verts:
            continue
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        x0 = int(math.floor(min(xs)))
        x1 = int(math.ceil(max(xs)))
        y0 = int(math.floor(min(ys)))
        y1 = int(math.ceil(max(ys)))
        for ix in range(x0, max(x1, x0 + 1)):
            for iy in range(y0, max(y1, y0 + 1)):
                cells.add((ix, iy))
    return frozenset(cells)


def _resolve_raster_fn():
    fn = _RASTER_FN[0]
    if fn is None:
        try:
            from baseline_greedy import _block_raster_cells
            fn = _block_raster_cells
            _RASTER_FN[0] = fn            # memoise only the successful resolve
        except Exception:
            fn = _fallback_block_cells    # retry the real import next call
    return fn


# Per-(block_data, orient) origin-raster cache.  The key includes
# id(block_data), stable for the lifetime of one solve (the blocks_data dicts
# live for the whole run).  A recycled id after gc could in principle serve
# STALE cells; harmless here because candidates are proposals only -- the
# polygon-exact checks downstream reject bad ones (worst case = a few wasted
# candidates).  Bounded: cleared wholesale when it outgrows the cap.
_ORIGIN_CELLS_CACHE: dict = {}
_ORIGIN_CACHE_MAX = 8192

# Small union cache for the placed-cell set.  The decode loops call the adapter
# once per ORIENTATION with the SAME placed list, and the union over placed
# blocks is the expensive part -- memoise it on the (id, x, y, orient)
# signature of the placed list.  Tiny, cleared wholesale when full.
_PLACED_UNION_CACHE: dict = {}
_PLACED_CACHE_MAX = 64


def _origin_cells(block_data, orient_idx, block_id, raster_fn):
    key = (id(block_data), int(block_id), int(orient_idx))
    cells = _ORIGIN_CELLS_CACHE.get(key)
    if cells is not None:
        return cells
    if _Block is None:
        return frozenset()
    blk = _Block(block_id=block_id if block_id >= 0 else 0,
                 block_data=block_data, x=0, y=0, orient_idx=orient_idx)
    cells = raster_fn(blk)
    if len(_ORIGIN_CELLS_CACHE) >= _ORIGIN_CACHE_MAX:
        _ORIGIN_CELLS_CACHE.clear()
    _ORIGIN_CELLS_CACHE[key] = cells
    return cells


def _placed_union_cells(placed_blocks, raster_fn):
    if not placed_blocks:
        return frozenset()
    try:
        key = tuple((id(b), b.x, b.y, b.orient_idx) for b in placed_blocks)
    except Exception:
        key = None
    if key is not None:
        cached = _PLACED_UNION_CACHE.get(key)
        if cached is not None:
            return cached
    cells = set()
    for b in placed_blocks:
        cells |= raster_fn(b)             # per-Block frozenset, cached upstream
    fs = frozenset(cells)
    if key is not None:
        if len(_PLACED_UNION_CACHE) >= _PLACED_CACHE_MAX:
            _PLACED_UNION_CACHE.clear()
        _PLACED_UNION_CACHE[key] = fs
    return fs


def column_drop_from_blocks(bay_w, bay_h, placed_blocks, block_data, orient_idx,
                            max_k=None, block_id=-1, stride=1):
    """Adapter from the solver's placed-Block representation to the cell-set
    core above.

    placed_blocks: list[utils.Block] already placed in the bay -- the SAME list
    the bbox generators receive (whether it is time-filtered, e.g. phase-1's
    active_in_bay, is the caller's policy, exactly as for _candidate_positions).
    block_data:    instance["blocks"][i] dict; orient_idx selects the shape
                   entry, mirroring _block_bbox(blk_data, oi).
    max_k:         candidate cap; None -> OGC_T5_CANDS_K (default 40).
    block_id:      optional real block id (used for Block construction and the
                   origin-raster cache key; -1 = anonymous).

    Uses baseline_greedy._block_raster_cells (per-Block cached) when available,
    else the coarse bbox-fill fallback.  Returns [(x, y), ...] integer reference
    positions, [] on any error (never raises)."""
    try:
        raster_fn = _resolve_raster_fn()
        cells0 = _origin_cells(block_data, orient_idx, block_id, raster_fn)
        if not cells0:
            return []
        placed_cells = _placed_union_cells(placed_blocks or [], raster_fn)
        k = _default_max_k() if max_k is None else int(max_k)
        return column_drop_candidates(bay_w, bay_h, placed_cells, cells0,
                                      max_k=k, stride=stride)
    except Exception:
        return []


# -----------------------------------------------------------------------------
# Merge helper for the integration sites
# -----------------------------------------------------------------------------

def merge_candidates(base, extra):
    """base positions first (original order preserved -- callers re-sort / cap
    with their own policy unchanged), then extra positions not already present.
    Never raises; on any error returns base unchanged (as a list)."""
    try:
        out = list(base)
        if not extra:
            return out
        seen = set(out)
        for p in extra:
            t = (int(p[0]), int(p[1]))
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out
    except Exception:
        try:
            return list(base)
        except Exception:
            return []
