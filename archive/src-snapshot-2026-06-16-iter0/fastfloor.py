"""Crane-aware fast floor: a z1=0-targeting, z3-friendly initial solution in ~20s.

Pipeline (single pass, no search):
  1. setup        -- bays / bay_u / feasible_bays (mirrors algorithm() setup).
  2. assignment   -- _cpsat_assignment (exact z2+z3, no geometry); greedy fallback.
  3. entry-targets-- per-bay cumulative CP-SAT (alpha=0.85): one interval per
                     block, demand = min-orientation bbox area, minimise total
                     tardiness -> {block: target entry t*}.
  3b. spill       -- anticipatory: bays whose TARGET tardiness is already >0 are
                     over-subscribed in area-time; move late-due blocks to a
                     feasible 0-tardiness bay with max area-time slack.
  4. decode       -- per bay: fixed-time decode RACE (F0-F3 placement-order
                     variants, lowest bay tardiness wins, tard==0
                     short-circuits) then legacy _decode_bay attempts
                     (order = t* asc, release_override = t*), bays in
                     parallel processes.
  4c. xbay        -- cross-bay fixed-time relocation of still-tardy blocks,
                     up to 3 passes (a vacated spot admits the next chain):
                     insert at entry=R/exit=R+P into another feasible bay
                     (existing layout untouched), net-gain gate
                     -w1*dz1 + w3*dz3 < 0; budget <= 4s.
  5. assemble     -- _build_operations + official check_feasibility.

Rationale (documented): z1 comes from release-peak simultaneous entry causing
crane serialisation while bays sit 75-94% empty -> spreading entries via the
cumulative target model + a single decode should land at/near z1=0.

This module only IMPORTS from myalgorithm / baseline_greedy / utils; it never
modifies them.
"""
from __future__ import annotations

import math
import os
import time

_T_IMPORT0 = time.monotonic()
from utils import Bay, Block, check_feasibility, _resolve_layers  # noqa: E402
from myalgorithm import (                                     # noqa: E402
    _cpsat_assignment, _decode_bay, _feasible_bays, _adapt_cap_for_bay,
    _cpsat_bay_timing_verified,
)
from baseline_greedy import (                                 # noqa: E402
    _build_operations, _block_bbox, _rasterize_layer_cells,
)
_IMPORT_S = time.monotonic() - _T_IMPORT0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _min_bbox_area(blk: dict) -> int:
    """Smallest-orientation bounding-box area (optimistic: the decoder is free
    to pick any orientation)."""
    best = None
    for oi in range(len(blk.get("shape", []) or [])):
        bb = _block_bbox(blk, oi)
        a = (bb[2] - bb[0]) * (bb[3] - bb[1])
        if best is None or a < best:
            best = a
    return max(1, int(best if best is not None else 1))


def _bay_targets(ids, blocks, bay, alpha, budget):
    """Per-bay cumulative entry-target model (no layout needed).

    Mirrors myalgorithm._cumulative_leveled_redecode_verified._cum_targets but
    starts from scratch: demand = min-orientation bbox area, hint = release.
    Returns ({block_id: target_entry}, total_target_tardiness) or (None, None).
    """
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None, None
    try:
        cap = max(1, int(bay.width * bay.height * alpha))
        m = cp_model.CpModel()
        H = (max(int(blocks[b]["due_date"]) for b in ids)
             + sum(int(blocks[b]["processing_time"]) for b in ids))
        e = {}; ivs = []; dem = []; tard = []
        for b in ids:
            blk = blocks[b]
            area = min(_min_bbox_area(blk), cap)
            R = int(blk["release_time"]); P = int(blk["processing_time"])
            D = int(blk["due_date"])
            ev = m.NewIntVar(R, H, f"e{b}"); e[b] = ev
            xv = m.NewIntVar(R, H + P, f"x{b}")
            ivs.append(m.NewIntervalVar(ev, P, xv, f"i{b}"))
            dem.append(area)
            tv = m.NewIntVar(0, H, f"t{b}"); m.Add(tv >= ev + P - D); tard.append(tv)
            m.AddHint(ev, R)
        m.AddCumulative(ivs, dem, cap)
        m.Minimize(sum(tard))
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = max(0.2, float(budget))
        s.parameters.num_search_workers = 4
        st = s.Solve(m)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, None
        return ({b: int(s.Value(e[b])) for b in ids}, float(s.ObjectiveValue()))
    except Exception:
        return None, None


def _greedy_assign(blocks, feasible_bays, bays_data):
    """Fallback assignment: per block (largest area-time first), pick the
    feasible bay minimising area-time pressure, tie-broken by preference."""
    n_bays = len(bays_data)
    load = [0.0] * n_bays
    cap = [float(d["width"] * d["height"]) for d in bays_data]
    assign = [-1] * len(blocks)
    order = sorted(range(len(blocks)),
                   key=lambda b: -_min_bbox_area(blocks[b])
                   * blocks[b]["processing_time"])
    for b in order:
        blk = blocks[b]
        at = _min_bbox_area(blk) * blk["processing_time"]
        cands = feasible_bays[b] or list(range(n_bays))
        best = min(cands, key=lambda j: ((load[j] + at) / cap[j],
                                         -blk["bay_preferences"][j]))
        assign[b] = best
        load[best] += at
    return assign


# ---------------------------------------------------------------------------
# Fixed-time decode: fix entry=R / exit=R+P FIRST (z1=0 by construction), then
# search positions only.  Geometry constraints exist ONLY between time-
# interacting pairs (conditions 1-5 below); non-overlapping intervals
# (eA <= aB or eB <= aA) are geometry-free -- same spot is reusable.
# Raster cells are the conservative per-layer superset from baseline_greedy.
# ---------------------------------------------------------------------------

def _local_layer_cells(blk: dict, oi: int) -> list[frozenset]:
    """Per-layer raster cells of orientation `oi` in LOCAL coordinates (ref =
    first vertex of first layer = (0, 0); see utils.Block).

    SCREENING ONLY.  Vertices are FLOATS (e.g. -5.1498), so integer-shifted
    local cells are NOT exactly equal to rasterising the float-translated
    world verts (verified mismatch on prob_1: 8 layers differ at the boundary;
    see tests/test_fastfloor_fixed_time.py).  Candidate scanning may use the
    cheap shift {(cx + x, cy + y)}, but every ACCEPTED placement is
    re-verified and stored with _world_layer_cells (direct rasterisation),
    which alone carries the conservative-superset soundness."""
    layers = _resolve_layers(blk["shape"][oi]["layers"])
    return [_rasterize_layer_cells(l) for l in layers]


def _world_layer_cells(block_obj: Block) -> list[frozenset]:
    """Per-layer raster cells of a PLACED Block in world coordinates --
    direct rasterisation of layers_at_pos(), the same conservative superset
    the baseline raster floor uses (sound vs the official Shapely check)."""
    return [_rasterize_layer_cells(l) for l in block_obj.layers_at_pos()]


def _ft_pair_ok(A: dict, aB: int, eB: int,
                B_layers: list, dx: int, dy: int, nB: int) -> bool:
    """Forbidden-predicate check between placed block A (world cells, fixed
    times) and candidate B (local cells shifted by integer (dx, dy)).

    obstruct(M, S) = exists k < n_layers(M), j in [k, n_layers(S)):
                     cells_M[k] & cells_S[j] != {}   ("S blocks M's move")
    collide(A, B)  = exists k < min(nA, nB): cells_A[k] & cells_B[k] != {}

    Forbidden (half-open stays [a, e)):
      1. aA <= aB < eA  -> obstruct(B, A)   (A blocks B's entry)
      2. aA <  eB <= eA -> obstruct(B, A)   (A blocks B's exit; co-exit incl.)
      3. aB <= aA < eB  -> obstruct(A, B)
      4. aB <  eA <= eB -> obstruct(A, B)
      5. aA < eB and aB < eA (open overlap) -> collide(A, B)
    """
    aA, eA = A["a"], A["e"]
    A_layers = A["layers"]; nA = A["n"]
    memo: dict[tuple, bool] = {}

    def hit(kb: int, ja: int) -> bool:
        """B layer kb (shifted) intersects A layer ja?"""
        r = memo.get((kb, ja))
        if r is None:
            Aj = A_layers[ja]
            r = any((cx + dx, cy + dy) in Aj for (cx, cy) in B_layers[kb])
            memo[(kb, ja)] = r
        return r

    if (aA <= aB < eA) or (aA < eB <= eA):          # conds 1-2: obstruct(B, A)
        for k in range(nB):
            for j in range(k, nA):
                if hit(k, j):
                    return False
    if (aB <= aA < eB) or (aB < eA <= eB):          # conds 3-4: obstruct(A, B)
        for k in range(nA):
            for j in range(k, nB):
                if hit(j, k):
                    return False
    if aA < eB and aB < eA:                          # cond 5: collide
        for k in range(min(nA, nB)):
            if hit(k, k):
                return False
    return True


def _ft_geom(blk: dict) -> list:
    """Per-orientation geometry of one block: (local layer cells, cell bbox,
    poly bbox, n_layers) per orientation, or None for orientations with no
    rasterisable layers.  Shared by the per-bay decode cache and stage 4c."""
    g = []
    for oi in range(len(blk.get("shape", []) or [])):
        try:
            layers = _local_layer_cells(blk, oi)
        except Exception:
            layers = []
        if not layers or not all(layers):
            g.append(None)
            continue
        allc = [c for lay in layers for c in lay]
        cbox = (min(c[0] for c in allc), min(c[1] for c in allc),
                max(c[0] for c in allc), max(c[1] for c in allc))
        g.append((layers, cbox, _block_bbox(blk, oi), len(layers)))
    return g


def _ft_interacting(placed: list, aB: int, eB: int) -> list:
    """Placed blocks with ANY of conditions 1-5 true vs (aB, eB)."""
    return [A for A in placed
            if (A["a"] < eB and aB < A["e"])
            or (A["a"] <= aB < A["e"]) or (A["a"] < eB <= A["e"])
            or (aB <= A["a"] < eB) or (aB < A["e"] <= eB)]


def _ft_search_pos(b, blk, geo, bay, aB, eB, At, deadline,
                   grid=False, ft=None):
    """Position search for block `b` at FIXED times (aB, eB) vs A_t only.

    Pass 1 -- BL-style abut candidates (walls + edges of A_t members).
    Pass 2 -- only when grid=True and every abut candidate failed: whole-bay
    integer grid scan, y asc -> x asc (BL first), stride 1 (2 when
    W*H > 40000), bbox bay-bounds implicit in the ranges.  Wins are counted
    in ft["grid_hits"].

    Shifted local cells screen the candidates; the winner is re-verified with
    direct world raster cells (float verts break exact shift equivariance --
    see _local_layer_cells).  Returns (x, y, oi, wlayers, wcbox) | None."""
    W, H = bay.width, bay.height

    def _verify(oi, dx, dy):
        """Direct-raster verification (load-bearing): re-run the pair
        predicates with the true world cells before accepting."""
        bl = Block(b, blk, dx, dy, oi)
        if not bay.contains_block(bl):
            return None                                  # final confirm
        wlayers = _world_layer_cells(bl)
        allc = [c for lay in wlayers for c in lay]
        wcbox = ((min(c[0] for c in allc), min(c[1] for c in allc),
                  max(c[0] for c in allc), max(c[1] for c in allc))
                 if allc else (0, 0, -1, -1))
        for A in At:
            acb = A["cbox"]
            if (wcbox[0] > acb[2] or acb[0] > wcbox[2]
                    or wcbox[1] > acb[3] or acb[1] > wcbox[3]):
                continue
            if not _ft_pair_ok(A, aB, eB, wlayers, 0, 0, len(wlayers)):
                return None
        return dx, dy, oi, wlayers, wcbox

    cands = []
    for oi, g in enumerate(geo):
        if g is None:
            continue
        pb = g[2]
        bbw = pb[2] - pb[0]; bbh = pb[3] - pb[1]
        if bbw > W + 1e-9 or bbh > H + 1e-9:
            continue
        xs = {int(math.ceil(-pb[0] - 1e-9)),            # left wall
              int(math.floor(W - pb[2] + 1e-9))}        # right wall
        for A in At:
            # right edge of A (B to its right) and left edge of A (B to
            # its left): abutting cell columns conservatively touch in
            # the raster, so offer both abut and abut+/-1.
            e = int(math.ceil(A["pbox"][2] - pb[0] - 1e-9))
            xs.add(e); xs.add(e + 1)
            w = int(math.floor(A["pbox"][0] - pb[2] + 1e-9))
            xs.add(w); xs.add(w - 1)
        for dx in xs:
            x0 = dx + pb[0]; x1 = dx + pb[2]
            if x0 < -1e-9 or x1 > W + 1e-9:
                continue
            dys = {int(math.ceil(-pb[1] - 1e-9))}        # floor
            for A in At:
                apb = A["pbox"]
                if apb[0] < x1 - 1e-9 and x0 < apb[2] - 1e-9:
                    # top of EVERY x-overlapping A (not just the max
                    # skyline): lets B rest on a lower block even when a
                    # taller one partially overlaps the span.  abut/abut+1
                    # (abutting raster cells conservatively touch).
                    d = int(math.ceil(apb[3] - pb[1] - 1e-9))
                    dys.add(d); dys.add(d + 1)
            for dy in dys:
                if dy + pb[1] < -1e-9 or dy + pb[3] > H + 1e-9:
                    continue
                cands.append((dy + pb[1], dx + pb[0], oi, dx, dy))
    cands.sort(key=lambda c: (c[0], c[1], c[2]))          # BL: (Y, X)
    del cands[4096:]   # bound the scan; lowest (Y, X) are the BL spots
    tried = set()
    for n_seen, (_, _, oi, dx, dy) in enumerate(cands):
        if (oi, dx, dy) in tried:
            continue
        tried.add((oi, dx, dy))
        if (n_seen & 63) == 0 and time.monotonic() >= deadline - 0.2:
            return None
        layers, cb, pb, nB = geo[oi]
        wcb = (cb[0] + dx, cb[1] + dy, cb[2] + dx, cb[3] + dy)
        ok = True
        for A in At:
            acb = A["cbox"]
            if (wcb[0] > acb[2] or acb[0] > wcb[2]
                    or wcb[1] > acb[3] or acb[1] > wcb[3]):
                continue                                 # bbox prefilter
            if not _ft_pair_ok(A, aB, eB, layers, dx, dy, nB):
                ok = False
                break
        if not ok:
            continue
        r = _verify(oi, dx, dy)
        if r is not None:
            return r
    if not grid:
        return None
    # -- grid fallback: every abut candidate failed -> exhaustive in-bay scan.
    stride = 1 if W * H <= 40000 else 2
    n_seen = 0
    for oi, g in enumerate(geo):
        if g is None:
            continue
        layers, cb, pb, nB = g
        dx_lo = int(math.ceil(-pb[0] - 1e-9))
        dx_hi = int(math.floor(W - pb[2] + 1e-9))
        dy_lo = int(math.ceil(-pb[1] - 1e-9))
        dy_hi = int(math.floor(H - pb[3] + 1e-9))
        if dx_hi < dx_lo or dy_hi < dy_lo:
            continue
        for dy in range(dy_lo, dy_hi + 1, stride):       # y asc -> x asc (BL)
            for dx in range(dx_lo, dx_hi + 1, stride):
                n_seen += 1
                if (n_seen & 63) == 0 and time.monotonic() >= deadline - 0.2:
                    return None
                if (oi, dx, dy) in tried:
                    continue                             # already failed abut
                wcb = (cb[0] + dx, cb[1] + dy, cb[2] + dx, cb[3] + dy)
                ok = True
                for A in At:
                    acb = A["cbox"]
                    if (wcb[0] > acb[2] or acb[0] > wcb[2]
                            or wcb[1] > acb[3] or acb[1] > wcb[3]):
                        continue                         # bbox prefilter
                    if not _ft_pair_ok(A, aB, eB, layers, dx, dy, nB):
                        ok = False
                        break
                if not ok:
                    continue
                r = _verify(oi, dx, dy)
                if r is not None:
                    if ft is not None:
                        ft["grid_hits"] = ft.get("grid_hits", 0) + 1
                    return r
    return None


def _ft_search_pos_lca(b, blk, geo, bay, aB, eB, At, deadline,
                       grid=False, ft=None, verify_cap=48, cand_cap=320):
    """Extreme-Point + Largest-Contact-Area position search at FIXED times.

    Drop-in for `_ft_search_pos` (same signature / return).  The BL-only placer
    returns the lowest (Y, X) feasible spot; this one packs DENSER: among all
    crane-feasible candidates it keeps the one maximising bbox contact perimeter
    with the co-present placed blocks + bay walls -- the SSP density lever
    (Shang & Gu 2017 / Koh 2008 LCA, Kwon & Lee 2015 diagonal-fill).  Denser
    co-present packing fits more blocks at z1=0 in a preferred bay -> fewer
    spills -> lower z3 (the dominant objective term on the loss instances).

    Candidate set (Extreme Points): for each orientation, x-anchors = bay walls
    + each placed block's left/right edge (abut +/- 1); per x-anchor, y-anchors =
    bay floor + ceiling (TR-slide) + the top/bottom of every placed block that
    x-overlaps there (BL-slide rest-on AND TR-slide hang-below).  Crane j>=k is
    validated with the SAME raster predicates as `_ft_search_pos`
    (`_ft_pair_ok` local-cell screen + `_world_layer_cells` re-verify), so the
    placement is exactly as crane-safe.

    Feasibility-superset of BL: the EP set contains every BL abut spot, and if
    nothing here verifies within budget it DELEGATES to `_ft_search_pos`
    (BL abut + optional grid).  So it never fits fewer blocks than BL -- it only
    re-ranks the feasible spots by density.  Returns (x, y, oi, wlayers, wcbox)
    | None."""
    W, H = bay.width, bay.height
    eps = 1e-6
    tol = 1.0 + 1e-6    # poly-coord abut tolerance (abutting raster cells touch)
    # Ranking band (OGC_UC_NEST_BAND, default 8).  Pure max-contact fragments the
    # residual free space for the ONLINE (EDD-ordered) sequence -> later blocks no
    # longer fit at z1=0 (measured: heavy bays got WORSE).  So rank BL-PRIMARY
    # (lowest y-band first, exactly the crane-friendly contiguous-free-space
    # property of `_ft_search_pos`) and use contact only to break ties WITHIN a
    # band -- fill floor gaps without climbing.  band=1 ~ pure BL; band>=H ~ pure
    # LCA.  Sweeps the BL<->LCA spectrum from one knob.
    try:
        _band = max(1, int(float(os.environ.get("OGC_UC_NEST_BAND", "8"))))
    except Exception:
        _band = 8

    def _contact(bx0, by0, bx1, by1):
        """Shared-boundary length of candidate bbox with bay walls + the
        co-present placed bboxes (the LCA density signal; higher = tighter)."""
        s = 0.0
        if bx0 <= eps:        s += (by1 - by0)
        if bx1 >= W - eps:    s += (by1 - by0)
        if by0 <= eps:        s += (bx1 - bx0)
        if by1 >= H - eps:    s += (bx1 - bx0)
        for A in At:
            ax0, ay0, ax1, ay1 = A["pbox"]
            if abs(bx1 - ax0) <= tol or abs(bx0 - ax1) <= tol:   # vertical abut
                ov = min(by1, ay1) - max(by0, ay0)
                if ov > 0:    s += ov
            if abs(by1 - ay0) <= tol or abs(by0 - ay1) <= tol:   # horizontal abut
                ov = min(bx1, ax1) - max(bx0, ax0)
                if ov > 0:    s += ov
        return s

    def _verify(oi, dx, dy):
        """Direct-raster confirm (load-bearing) -- identical to _ft_search_pos."""
        bl = Block(b, blk, dx, dy, oi)
        if not bay.contains_block(bl):
            return None
        wlayers = _world_layer_cells(bl)
        allc = [c for lay in wlayers for c in lay]
        wcbox = ((min(c[0] for c in allc), min(c[1] for c in allc),
                  max(c[0] for c in allc), max(c[1] for c in allc))
                 if allc else (0, 0, -1, -1))
        for A in At:
            acb = A["cbox"]
            if (wcbox[0] > acb[2] or acb[0] > wcbox[2]
                    or wcbox[1] > acb[3] or acb[1] > wcbox[3]):
                continue
            if not _ft_pair_ok(A, aB, eB, wlayers, 0, 0, len(wlayers)):
                return None
        return dx, dy, oi, wlayers, wcbox

    cands = []
    for oi, g in enumerate(geo):
        if g is None:
            continue
        _layers, _cb, pb, _nB = g
        bbw = pb[2] - pb[0]; bbh = pb[3] - pb[1]
        if bbw > W + 1e-9 or bbh > H + 1e-9:
            continue
        xs = {int(math.ceil(-pb[0] - 1e-9)),            # left wall
              int(math.floor(W - pb[2] + 1e-9))}        # right wall
        for A in At:
            e = int(math.ceil(A["pbox"][2] - pb[0] - 1e-9))   # right of A
            xs.add(e); xs.add(e + 1)
            w = int(math.floor(A["pbox"][0] - pb[2] + 1e-9))  # left of A
            xs.add(w); xs.add(w - 1)
        for dx in xs:
            x0 = dx + pb[0]; x1 = dx + pb[2]
            if x0 < -1e-9 or x1 > W + 1e-9:
                continue
            dys = {int(math.ceil(-pb[1] - 1e-9)),            # floor (BL)
                   int(math.floor(H - pb[3] + 1e-9))}        # ceiling (TR)
            for A in At:
                apb = A["pbox"]
                if apb[0] < x1 - 1e-9 and x0 < apb[2] - 1e-9:  # x-overlaps here
                    d = int(math.ceil(apb[3] - pb[1] - 1e-9))      # rest on A
                    dys.add(d); dys.add(d + 1)
                    d2 = int(math.floor(apb[1] - pb[3] + 1e-9))    # hang below A
                    dys.add(d2); dys.add(d2 - 1)
            for dy in dys:
                y0 = dy + pb[1]; y1 = dy + pb[3]
                if y0 < -1e-9 or y1 > H + 1e-9:
                    continue
                sc = _contact(x0, y0, x1, y1)
                cands.append((int(y0 // _band), -sc, y0, x0, oi, dx, dy))
    if not cands:
        return _ft_search_pos(b, blk, geo, bay, aB, eB, At, deadline,
                              grid=grid, ft=ft)
    cands.sort()                            # y-band asc, contact desc, then BL
    del cands[cand_cap:]
    tried = set()
    n_ver = 0
    for _, _, _, _, oi, dx, dy in cands:
        if (oi, dx, dy) in tried:
            continue
        tried.add((oi, dx, dy))
        if time.monotonic() >= deadline - 0.2:
            break
        layers, cb, pb, nB = geo[oi]
        wcb = (cb[0] + dx, cb[1] + dy, cb[2] + dx, cb[3] + dy)
        ok = True
        for A in At:
            acb = A["cbox"]
            if (wcb[0] > acb[2] or acb[0] > wcb[2]
                    or wcb[1] > acb[3] or acb[1] > wcb[3]):
                continue                                       # bbox prefilter
            if not _ft_pair_ok(A, aB, eB, layers, dx, dy, nB):
                ok = False
                break
        if not ok:
            continue
        r = _verify(oi, dx, dy)
        n_ver += 1
        if r is not None:
            if ft is not None:
                ft["lca_hits"] = ft.get("lca_hits", 0) + 1
            return r                  # contact-desc order -> first feasible = LCA
        if n_ver >= verify_cap:
            break
    # No extreme-point candidate verified in budget -> BL abut + grid backstop.
    return _ft_search_pos(b, blk, geo, bay, aB, eB, At, deadline,
                          grid=grid, ft=ft)


_FT_ORDER_KEYS = ("F0", "F1", "F2", "F3")


def _ft_order(ids, blocks, key):
    """Placement order for the fixed-time decode race (tie-break variants).
    F0: entry asc, footprint area desc (v4 default)   F1: entry asc, due asc
    F2: due asc, entry asc                            F3: entry asc, area asc
    All deterministic -> the race also damps run-to-run decode variance."""
    if key == "F1":
        return sorted(ids, key=lambda b: (int(blocks[b]["release_time"]),
                                          int(blocks[b]["due_date"])))
    if key == "F2":
        return sorted(ids, key=lambda b: (int(blocks[b]["due_date"]),
                                          int(blocks[b]["release_time"])))
    if key == "F3":
        return sorted(ids, key=lambda b: (int(blocks[b]["release_time"]),
                                          _min_bbox_area(blocks[b])))
    return sorted(ids, key=lambda b: (int(blocks[b]["release_time"]),
                                      -_min_bbox_area(blocks[b])))


def _fixed_time_decode(bay, bay_idx, ids, blocks_data, deadline,
                       order_key="F0"):
    """Time-first decode of one bay: every block targets entry=R, exit=R+P
    (zero tardiness when due >= R+P), and only the POSITION is searched against
    the time-interacting placed set.  Fallbacks: shift entry to placed exit
    times ascending (delayed), then a guaranteed empty window (forced; only on
    deadline pressure -- the last exit candidate already has zero interactions).

    `order_key` picks the placement order (F0-F3, see _ft_order).
    Returns (asgn | None, ft_stats); asgn matches the _decode_bay record format.
    ft_stats = {placed_at_R, delayed, forced, grid_hits, ft_tard, variant}."""
    ft = {"placed_at_R": 0, "delayed": 0, "forced": 0, "grid_hits": 0,
          "ft_tard": 0.0,
          "variant": ("X" if isinstance(order_key, (list, tuple))
                      else order_key)}
    blocks = blocks_data
    # An explicit order list (redecode loop's seeded shuffles / slack orders)
    # bypasses the F0-F3 catalog; everything downstream is order-agnostic.
    order = (list(order_key) if isinstance(order_key, (list, tuple))
             else _ft_order(ids, blocks, order_key))
    geom_cache: dict[int, list] = {}
    placed: list[dict] = []   # {a, e, layers(world), n, cbox(cells), pbox(poly)}
    result: dict[int, dict] = {}

    def _geom(b):
        g = geom_cache.get(b)
        if g is None:
            g = _ft_geom(blocks[b])
            geom_cache[b] = g
        return g

    for b in order:
        blk = blocks[b]
        R = int(blk["release_time"]); P = int(blk["processing_time"])
        D = int(blk["due_date"])
        aB, eB = R, R + P
        pos = None
        mode = "placed_at_R"
        if time.monotonic() < deadline - 0.2:
            # at R: abut candidates, then whole-bay grid scan (grid=True --
            # fires only for conflicted blocks whose abut spots all failed).
            pos = _ft_search_pos(b, blk, _geom(b), bay, aB, eB,
                                 _ft_interacting(placed, aB, eB), deadline,
                                 grid=True, ft=ft)
            if pos is None:
                # delayed: walk entry over placed exit times ascending
                for t in sorted({A["e"] for A in placed if A["e"] > R}):
                    if time.monotonic() >= deadline - 0.2:
                        break
                    aB, eB = t, t + P
                    pos = _ft_search_pos(b, blk, _geom(b), bay, aB, eB,
                                         _ft_interacting(placed, aB, eB),
                                         deadline)
                    if pos is not None:
                        mode = "delayed"
                        break
        if pos is None:
            # forced empty window: entry after every placed exit -> zero
            # interactions; any in-bay BL spot works.
            aB = max([R] + [A["e"] for A in placed])
            eB = aB + P
            pos = _ft_search_pos(b, blk, _geom(b), bay, aB, eB, [], deadline,
                                 grid=True, ft=ft)
            if pos is None:
                return None, ft                              # cannot fit bay
            mode = "forced"
        dx, dy, oi, wlayers, wcbox = pos
        pb = _geom(b)[oi][2]
        placed.append({
            "a": aB, "e": eB, "n": len(wlayers),
            "layers": wlayers,                               # DIRECT cells
            "cbox": wcbox,
            "pbox": (pb[0] + dx, pb[1] + dy, pb[2] + dx, pb[3] + dy),
        })
        result[b] = {"block_id": b, "bay_id": bay_idx, "x": int(dx),
                     "y": int(dy), "orient_idx": int(oi),
                     "entry_time": int(aB), "exit_time": int(eB)}
        ft[mode] += 1
        ft["ft_tard"] += max(0.0, eB - D)
    return result, ft


# ---------------------------------------------------------------------------
# Parallel decode (run_parallel_bay_decode does NOT support custom order /
# release_override, so we ship our own spawn-safe worker -- same pattern as
# parallel_decode._bay_decode_worker).
# ---------------------------------------------------------------------------

def _decode_attempts(bay, bay_idx, ids, attempts, blocks_data, deadline):
    """Best-of-N single-bay decode.  `attempts` items are tagged:
      ("fixed", key)              -> _fixed_time_decode RACE entry (order
                                     variant F0-F3; bare ("fixed",) == F0)
      ("decode", order, ro, cap)  -> _decode_bay best-of (legacy path)
    Each attempt is deadline-bounded; lowest-tardiness complete result wins,
    tard<=0 short-circuits (remaining variants AND legacy are skipped).
    Mirrors the cum_level multi-order loop (myalgorithm.py:2980-3016).
    Returns (best | None, ft_stats | None); ft_stats is the best fixed
    variant's stats (+"variant" key, +"won")."""
    best = None
    best_tard = math.inf
    best_src = None
    ft_stats = None
    ft_best_tard = math.inf

    def _run(att, att_dl):
        nonlocal best, best_tard, best_src, ft_stats, ft_best_tard
        if att[0] == "fixed":
            key = att[1] if len(att) > 1 else "F0"
            res, ft = _fixed_time_decode(bay, bay_idx, ids, blocks_data,
                                         att_dl, order_key=key)
            if ft_stats is None:
                ft_stats = ft   # diagnostics survive even if all variants fail
        else:
            _, order, ro, cap = att
            res, _forced = _decode_bay(bay, bay_idx, list(order), blocks_data,
                                       deadline=att_dl, cand_cap=cap,
                                       release_override=ro)
        if res is None or len(res) != len(ids):
            return
        tard = sum(max(0, res[b]["exit_time"] - blocks_data[b]["due_date"])
                   for b in ids)
        if att[0] == "fixed" and tard < ft_best_tard:
            ft_best_tard, ft_stats = tard, ft
        if tard < best_tard:
            best, best_tard, best_src = res, tard, att[0]

    # The first fixed variant keeps the full window (v4-equivalent floor).
    # If it was FAST (uncongested bay) the remaining variants race next --
    # they will be similarly fast; if it was SLOW (congested bay, heavy
    # delayed walks / grid scans) the race cannot win there anyway, so legacy
    # runs first and the leftover variants take small slices at the tail.
    fixed_atts = [a for a in attempts if a[0] == "fixed"]
    legacy_atts = [a for a in attempts if a[0] != "fixed"]
    order = list(attempts)
    if fixed_atts:
        t_f0 = time.monotonic()
        _run(fixed_atts[0], deadline)
        rest = fixed_atts[1:]
        order = ((rest + legacy_atts)
                 if time.monotonic() - t_f0 <= 1.0
                 else (legacy_atts + rest))
    for att in order:
        if best_tard <= 0 or time.monotonic() >= deadline - 0.3:
            break
        if att[0] == "fixed":
            # capped slice: a variant past its slice returns incomplete and
            # is simply skipped (never starves the other attempts).
            rem = deadline - time.monotonic()
            att_dl = time.monotonic() + min(rem, max(0.8, 0.15 * rem))
        else:
            att_dl = deadline
        _run(att, att_dl)
    if ft_stats is not None:
        ft_stats["won"] = (best_src == "fixed")
    return best, ft_stats


def _ff_decode_worker(task):
    """Decode ONE bay (best-of-N orders) in a child process.

    Top-level so Windows spawn can pickle it.  `deadline` is a monotonic
    timestamp -- comparable across processes (QPC / CLOCK_MONOTONIC are
    system-wide), so the worker self-bounds and always returns in time by
    force-placing the tail (feasible, pays tardiness)."""
    try:
        bay_idx, prob_info, ids, attempts, deadline = task
        from utils import Bay as _Bay
        bay = _Bay.from_dict(prob_info["bays"][bay_idx], int(bay_idx))
        blocks_data = prob_info["blocks"]
        res, ft = _decode_attempts(bay, int(bay_idx), ids, attempts,
                                   blocks_data, deadline)
        if res is None:
            return None
        return int(bay_idx), res, ft
    except Exception:
        return None


def _decode_bays_parallel(prob_info, bay_jobs, deadline, n_workers):
    """bay_jobs: list of (bay_idx, ids, attempts).
    Returns {bay_idx: ({block_id: asgn}, ft_stats | None)} for bays that
    finished, possibly partial on timeout (parent fills the rest
    sequentially)."""
    import multiprocessing as mp
    budget = deadline - time.monotonic()
    if budget <= 3.0 or len(bay_jobs) < 2 or n_workers < 2:
        return {}
    # Workers self-bound a little before the parent pool timeout so results
    # can be pickled back instead of being lost to pool.terminate().
    worker_deadline = deadline - 0.7
    tasks = [(j, prob_info, ids, attempts, worker_deadline)
             for j, ids, attempts in bay_jobs]
    ctx = mp.get_context("spawn")
    out = {}
    pool = None
    try:
        pool = ctx.Pool(processes=min(n_workers, len(tasks)))
        async_res = pool.map_async(_ff_decode_worker, tasks)
        try:
            results = async_res.get(timeout=max(0.0, deadline - time.monotonic()))
        except mp.TimeoutError:
            results = None
        for r in (results or []):
            if r is not None:
                out[r[0]] = (r[1], r[2])
    except Exception:
        pass
    finally:
        if pool is not None:
            try:
                pool.terminate()
            except Exception:
                pass
            try:
                pool.join()
            except Exception:
                pass
    return out


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def build_fast_floor(prob_info: dict, timelimit: float = 20.0,
                     n_workers: int = 4, log=None,
                     ban: dict | None = None) -> tuple[dict | None, dict]:
    """Build a crane-aware fast floor.  Returns (solution|None, stats).

    ban: optional {block_id: bay_id} — exclude that bay from the block's
    feasible set for THIS build (assignment-level tardy feedback: the caller
    bans the bays where a previous build's blocks came out tardy, so the
    re-assignment + full re-decode moves exactly the blocks that failed)."""
    t0 = time.monotonic()
    deadline = t0 + max(5.0, float(timelimit))
    T = max(5.0, float(timelimit))
    _log = log if callable(log) else (lambda *_: None)

    blocks = prob_info["blocks"]
    bays_data = prob_info["bays"]
    n = len(blocks)
    n_bays = len(bays_data)
    stats = {"n": n, "n_bays": n_bays, "import_s": round(_IMPORT_S, 3),
             "spill_moves": 0, "feasible": False}

    # -- 1. setup (mirrors algorithm() lines ~4727-4746) ----------------------
    bays = [Bay.from_dict(d, i) for i, d in enumerate(bays_data)]
    bay_areas = [d["width"] * d["height"] for d in bays_data]
    avg_area = sum(bay_areas) / n_bays
    bay_u = [avg_area / a for a in bay_areas]
    feasible_bays = _feasible_bays(blocks, bays)
    if ban:
        _fb2 = []
        for b in range(n):
            fb = feasible_bays[b] or list(range(n_bays))
            if b in ban and len(fb) > 1 and ban[b] in fb:
                fb = [j for j in fb if j != ban[b]]
            _fb2.append(fb)
        feasible_bays = _fb2
        stats["ban_n"] = len(ban)

    # -- 2. assignment ---------------------------------------------------------
    # Optional area-time capacity gate (OGC_FF_ASSIGN_CAP). Unset/empty/"0" ->
    # None (current behavior, bit-identical). Bare "1" -> 0.85 (sensible default
    # alpha). Any other float (e.g. "0.85") -> that alpha. Parse failures -> None.
    _cap_alpha = None
    try:
        _capraw = (os.environ.get("OGC_FF_ASSIGN_CAP", "") or "").strip()
        if _capraw and _capraw != "0":
            _cap_alpha = 0.85 if _capraw == "1" else float(_capraw)
            if not (0.0 < _cap_alpha <= 1.5):
                _cap_alpha = None
    except Exception:
        _cap_alpha = None
    # Magnet-bay tightening (OGC_FF_CAP_TIGHT=<factor in (0,1)>, default OFF):
    # the un-removable residual z1 lives in ONE preference-magnet bay (prob_20
    # bay1: 62 blocks top-pref = 827% area-time; prob_14 bay3 analogous).  A
    # uniformly tighter alpha (0.75 sweep) pays z3 across EVERY bay; instead
    # detect bays whose top-preference area-time pressure is >2x the median
    # and tighten ONLY their cap -> the assignment spreads exactly the blocks
    # that must leave.  Passed to _cpsat_assignment as a per-bay alpha list.
    if _cap_alpha is not None:
        try:
            _tg_raw = (os.environ.get("OGC_FF_CAP_TIGHT", "") or "").strip()
            _tg = float(_tg_raw) if _tg_raw and _tg_raw != "0" else None
            if _tg is not None and not (0.0 < _tg < 1.0):
                _tg = None
        except Exception:
            _tg = None
        if _tg is not None:
            _press = [0.0] * n_bays
            for _b, _blk in enumerate(blocks):
                _prefs = _blk["bay_preferences"]
                _jt = max(range(n_bays), key=lambda k: _prefs[k])
                _press[_jt] += (_min_bbox_area(_blk)
                                * _blk["processing_time"]) / max(
                                    1.0, float(bay_areas[_jt]))
            _med = sorted(_press)[n_bays // 2]
            _mag = [j for j in range(n_bays)
                    if _press[j] > 2.0 * max(1e-9, _med)]
            if _mag:
                _cap_alpha = [(_cap_alpha * _tg if j in _mag else _cap_alpha)
                              for j in range(n_bays)]
                stats["cap_tight_bays"] = _mag
                _log(f"[ff] cap_tight bays={_mag} press="
                     f"{[round(p, 2) for p in _press]}")
    t = time.monotonic()
    assign = _cpsat_assignment(prob_info, bays, feasible_bays, bay_u,
                               time_budget=min(3.0, 0.15 * T),
                               cap_alpha=_cap_alpha)
    stats["assign_src"] = "cpsat"
    if assign is None:
        assign = _greedy_assign(blocks, feasible_bays, bays_data)
        stats["assign_src"] = "greedy"
    stats["assign_s"] = round(time.monotonic() - t, 3)
    _log(f"[ff] assign={stats['assign_src']} ({stats['assign_s']}s)")

    bay_ids = [[] for _ in range(n_bays)]
    for b, j in enumerate(assign):
        bay_ids[j].append(b)
    non_empty = [j for j in range(n_bays) if bay_ids[j]]

    # -- 3. entry-targets (alpha=0.85) ------------------------------------------
    t = time.monotonic()
    stage_budget = min(2.0, 0.10 * T)
    per_bay = max(0.3, stage_budget / max(1, len(non_empty)))
    ALPHA = 0.85
    targets = {}   # j -> {block_id: t*} | None
    bay_tard = {}  # j -> target tardiness | None
    for j in non_empty:
        tg, td = _bay_targets(bay_ids[j], blocks, bays[j], ALPHA, per_bay)
        targets[j] = tg
        bay_tard[j] = td

    # -- 3b. anticipatory spill --------------------------------------------------
    at_load = [0.0] * n_bays
    for j in non_empty:
        for b in bay_ids[j]:
            at_load[j] += _min_bbox_area(blocks[b]) * blocks[b]["processing_time"]
    spill_deadline = time.monotonic() + stage_budget  # bounded extra rounds
    for _round in range(2):
        tardy = [j for j in non_empty
                 if bay_tard.get(j) is not None and bay_tard[j] > 0]
        if not tardy or time.monotonic() >= spill_deadline:
            break
        touched = set()
        for j in sorted(tardy, key=lambda x: -bay_tard[x]):
            move_cap = max(2, len(bay_ids[j]) // 10)
            moved = 0
            for b in sorted(bay_ids[j], key=lambda x: -blocks[x]["due_date"]):
                if moved >= move_cap:
                    break
                dests = [k for k in (feasible_bays[b] or range(n_bays))
                         if k != j and bay_tard.get(k) == 0]
                if not dests:
                    continue
                blk = blocks[b]
                at = _min_bbox_area(blk) * blk["processing_time"]
                # max area-time slack == min pressure; prefer higher S on ties
                dest = min(dests, key=lambda k: ((at_load[k] + at) / bay_areas[k],
                                                 -blk["bay_preferences"][k]))
                bay_ids[j].remove(b)
                bay_ids[dest].append(b)
                assign[b] = dest
                at_load[j] -= at
                at_load[dest] += at
                touched.add(j); touched.add(dest)
                moved += 1
                stats["spill_moves"] += 1
        if not touched:
            break
        rebudget = max(0.3, (spill_deadline - time.monotonic())
                       / max(1, len(touched)))
        for j in touched:
            if not bay_ids[j]:
                targets[j] = {}; bay_tard[j] = 0.0
                continue
            tg, td = _bay_targets(bay_ids[j], blocks, bays[j], ALPHA, rebudget)
            targets[j] = tg
            bay_tard[j] = td
    non_empty = [j for j in range(n_bays) if bay_ids[j]]
    stats["targets_s"] = round(time.monotonic() - t, 3)
    stats["target_tard"] = {j: bay_tard.get(j) for j in non_empty}
    _log(f"[ff] targets ({stats['targets_s']}s) tard={stats['target_tard']} "
         f"spill={stats['spill_moves']}")

    # -- 4. decode (best-of-N crane-safe orders per bay, bays in parallel) -------
    t = time.monotonic()
    TIMING_RESERVE = 4.0  # reserved for the CP-SAT re-timing pass (5b)
    decode_deadline = deadline - 2.5 - TIMING_RESERVE
    # When the worst-bay redecode (4d) is armed, carve its slice out of the
    # decode window UP FRONT: the decode race budget-fills to its deadline, so
    # without this the 4d loop never gets a single try (measured rd_tries=0 at
    # T=20 AND T=35).  T>=30 ONLY: at T=20 any carve robs the initial race and
    # the 1.5s re-roll slices cannot beat it anyway (measured: ft 36->62,
    # retiming squeezed out, z1 15-18 -> 20-29).  This is a LONG-tl lever
    # (caller raises OGC_FASTFLOOR_S); the short-tl floor stays untouched.
    _rd_on = ((os.environ.get("OGC_FF_REDECODE", "") or "").strip()
              not in ("", "0") and T >= 30.0)
    if _rd_on:
        decode_deadline -= min(12.0, max(4.0, 0.20 * T))
    SPAWN_MARGIN = 1.5  # child import (myalgorithm via fastfloor) + pickling
    bay_jobs = []
    decode_caps = {}
    for j in non_empty:
        ids = bay_ids[j]
        tg = targets.get(j)
        edd = sorted(ids, key=lambda b: blocks[b]["due_date"])
        # Banking cap: a fast capped first attempt guarantees a fully-searched
        # candidate, then uncapped attempts (deadline-bounded -> force-place
        # tail) spend the remaining window; best-of by bay tardiness.
        fast_budget = max(0.5, (decode_deadline - time.monotonic()
                                - SPAWN_MARGIN - 0.7) * 0.25)
        cap = _adapt_cap_for_bay(len(ids), fast_budget, 0)
        decode_caps[j] = cap
        # time-first decode race always tried first (F0-F3 order variants)
        attempts = [("fixed", k) for k in _FT_ORDER_KEYS]
        if tg:
            o1 = sorted(ids, key=lambda b: (tg[b], blocks[b]["due_date"]))
            o2 = sorted(ids, key=lambda b: (blocks[b]["due_date"], tg[b]))
            if cap > 0:
                attempts.append(("decode", o1, dict(tg), cap))
            attempts.append(("decode", o1, dict(tg), 0))
            attempts.append(("decode", o2, dict(tg), 0))
            attempts.append(("decode", edd, None, 0))
        else:
            if cap > 0:
                attempts.append(("decode", edd, None, cap))
            attempts.append(("decode", edd, None, 0))
        bay_jobs.append((j, ids, attempts))
    stats["decode_cap"] = decode_caps

    par = _decode_bays_parallel(prob_info, bay_jobs, decode_deadline,
                                n_workers)
    results = {}
    ft_all = {}
    for j, (res, ft) in par.items():
        results[j] = res
        if ft is not None:
            ft_all[j] = ft
    stats["decode_mode"] = "parallel" if results else "sequential"
    # Sequential pass for whatever the pool did not deliver (or all of it).
    # ALWAYS deadline-bounded: past the window each bay gets a short slice so
    # _decode_bay force-places the tail (feasible) instead of running unbounded.
    for j, ids, attempts in bay_jobs:
        if j in results:
            continue
        seq_dl = max(decode_deadline, time.monotonic() + 1.0)
        res, ft = _decode_attempts(bays[j], j, ids, attempts, blocks, seq_dl)
        if ft is not None:
            ft_all[j] = ft
        if res is None or len(res) != len(ids):
            stats["decode_s"] = round(time.monotonic() - t, 3)
            stats["total_s"] = round(time.monotonic() - t0, 3)
            stats["reason"] = f"decode_failed bay {j}"
            return None, stats
        results[j] = res
    stats["decode_s"] = round(time.monotonic() - t, 3)
    stats["fixed_time"] = ft_all
    ft_agg = {k: sum(ft.get(k, 0) for ft in ft_all.values())
              for k in ("placed_at_R", "delayed", "forced", "grid_hits")}
    ft_agg["ft_tard"] = round(sum(ft.get("ft_tard", 0.0)
                                  for ft in ft_all.values()), 1)
    ft_agg["won"] = sum(1 for ft in ft_all.values() if ft.get("won"))
    vw = {}
    for ftj in ft_all.values():
        if ftj.get("won") and ftj.get("variant"):
            vw[ftj["variant"]] = vw.get(ftj["variant"], 0) + 1
    ft_agg["variant_wins"] = vw
    stats["fixed_time_agg"] = ft_agg
    _log(f"[ff] decode={stats['decode_mode']} caps={decode_caps} "
         f"({stats['decode_s']}s) fixed={ft_agg}")

    # -- 4c. cross-bay fixed-time relocation of tardy blocks (multi-pass) --------
    # A tardy block keeps entry=R/exit=R+P but moves to ANOTHER feasible bay
    # whose existing layout (times fixed) admits it; nobody else moves, so
    # dz1 = -(tard - new_tard) and dz3 = pref_cur - pref_cand are EXACT (z2
    # ignored -- the final official check still gates the whole solution).
    # Up to 3 passes: a block leaving bay j frees raster cells there, so a
    # pass-1 reject may fit on pass 2 (chains).  Stop when a pass moves 0.
    # The vacated bay's other tardy blocks are NOT re-timed here; the 5b
    # re-timing pass picks that slack up.
    t = time.monotonic()
    stats["xbay_moves"] = 0
    xbay_grid = {"grid_hits": 0}
    wts = prob_info.get("weights", {})
    w1 = wts.get("w1", 1.0); w3 = wts.get("w3", 1.0)

    def _collect_tardy():
        tardy = []
        for j in list(results):
            for b, a in results[j].items():
                td = a["exit_time"] - blocks[b]["due_date"]
                if td > 0:
                    tardy.append((td, b, j))
        tardy.sort(key=lambda x: (-x[0], x[1]))
        return tardy

    xbay_dl = min(time.monotonic() + 4.0, deadline - TIMING_RESERVE - 1.5)
    placed_cache: dict[int, list] = {}   # j -> placed records (+"b" tag)

    def _bay_placed(j):
        pl = placed_cache.get(j)
        if pl is None:
            pl = []
            for b2, a2 in results.get(j, {}).items():
                blk2 = blocks[b2]
                bl2 = Block(b2, blk2, a2["x"], a2["y"], a2["orient_idx"])
                wlayers = _world_layer_cells(bl2)
                allc = [c for lay in wlayers for c in lay]
                cbox = ((min(c[0] for c in allc), min(c[1] for c in allc),
                         max(c[0] for c in allc), max(c[1] for c in allc))
                        if allc else (0, 0, -1, -1))
                pb2 = _block_bbox(blk2, a2["orient_idx"])
                pl.append({"b": b2, "a": a2["entry_time"],
                           "e": a2["exit_time"], "n": len(wlayers),
                           "layers": wlayers, "cbox": cbox,
                           "pbox": (pb2[0] + a2["x"], pb2[1] + a2["y"],
                                    pb2[2] + a2["x"], pb2[3] + a2["y"])})
            placed_cache[j] = pl
        return pl

    stats["xbay_pass_moves"] = []
    n_tardy0 = None
    for _pass in range(3):
        tardy = _collect_tardy()
        if n_tardy0 is None:
            n_tardy0 = len(tardy)
        if not tardy or xbay_dl - time.monotonic() <= 0.3:
            break
        pass_moves = 0
        for td, b, cj in tardy:
            if time.monotonic() >= xbay_dl - 0.1:
                break
            # per-block slice: one unplaceable high-td head must not burn the
            # whole window with failed grid scans (easy movers come after it).
            blk_dl = min(xbay_dl, time.monotonic() + 0.5)
            blk = blocks[b]
            R = int(blk["release_time"]); P = int(blk["processing_time"])
            D = int(blk["due_date"])
            new_td = max(0, R + P - D)   # fixed-time tardiness in ANY bay
            prefs = blk["bay_preferences"]
            geo = _ft_geom(blk)
            for k in sorted((x for x in feasible_bays[b] if x != cj),
                            key=lambda x: -prefs[x]):
                delta = -w1 * (td - new_td) + w3 * (prefs[cj] - prefs[k])
                if delta >= 0:
                    break   # prefs desc -> no later candidate is a net gain
                At = _ft_interacting(_bay_placed(k), R, R + P)
                pos = _ft_search_pos(b, blk, geo, bays[k], R, R + P, At,
                                     blk_dl, grid=True, ft=xbay_grid)
                if pos is None:
                    continue
                dx, dy, oi, wlayers, wcbox = pos
                results[cj].pop(b)
                if cj in placed_cache:
                    placed_cache[cj] = [A for A in placed_cache[cj]
                                        if A.get("b") != b]
                if k not in results:
                    results[k] = {}
                    non_empty.append(k)
                results[k][b] = {"block_id": b, "bay_id": int(k),
                                 "x": int(dx), "y": int(dy),
                                 "orient_idx": int(oi),
                                 "entry_time": int(R),
                                 "exit_time": int(R + P)}
                pb = _block_bbox(blk, oi)
                _bay_placed(k).append({"b": b, "a": R, "e": R + P,
                                       "n": len(wlayers), "layers": wlayers,
                                       "cbox": wcbox,
                                       "pbox": (pb[0] + dx, pb[1] + dy,
                                                pb[2] + dx, pb[3] + dy)})
                stats["xbay_moves"] += 1
                pass_moves += 1
                _log(f"[ff] xbay b={b} {cj}->{k} tard {td}->{new_td} "
                     f"dpref={prefs[k] - prefs[cj]}")
                break
        stats["xbay_pass_moves"].append(pass_moves)
        if pass_moves == 0:
            break
    stats["xbay_grid_hits"] = xbay_grid["grid_hits"]
    stats["xbay_s"] = round(time.monotonic() - t, 3)
    if n_tardy0:
        _log(f"[ff] xbay moves={stats['xbay_moves']}/{n_tardy0} "
             f"passes={stats['xbay_pass_moves']} "
             f"grid_hits={stats['xbay_grid_hits']} ({stats['xbay_s']}s)")

    # -- 4d. worst-bay focused REDECODE (OGC_FF_REDECODE, default OFF) -----------
    # Attribution (2026-06-12, prob_20 x3): the assignment's target tardiness is
    # 0.0 on EVERY bay, yet the decoded floor lands at z1=18/18/41 -- the decode
    # is both the level and the variance source.  Root cause: in the per-bay
    # race the non-first fixed variants only get a 0.15*rem slice, so on a
    # congested bay (prob_20 bay1) they return incomplete and are skipped.
    # This loop re-rolls the WORST bay with FULL-window fixed variants plus
    # fresh order diversity (slack-asc + seeded shuffles), adopting only a
    # strictly lower bay tardiness.  Layout swaps within one bay keep z2/z3
    # identical; the official check (step 5) still gates the whole solution.
    if _rd_on:
        import random as _random
        t = time.monotonic()
        stats["redecode_gain"] = 0.0
        stats["redecode_tries"] = 0
        # Leave room for assemble + official check (n-scaled) + the 5b
        # re-timing pass: with only a -1.0 margin the check ate the timing
        # window (pre_timing=None on every armed run).
        _rd_dl = (deadline - TIMING_RESERVE - 1.0
                  - min(3.0, 2e-5 * n * n + 0.5))
        _rd_tried: dict[int, int] = {}
        while time.monotonic() < _rd_dl - 0.8:
            _per_tard = {}
            for j in non_empty:
                _per_tard[j] = sum(
                    max(0.0, a["exit_time"] - blocks[b]["due_date"])
                    for b, a in results.get(j, {}).items())
            _cand = [(td, j) for j, td in _per_tard.items()
                     if td > 0.5 and _rd_tried.get(j, 0) < 4]
            if not _cand:
                break
            _td0, _j = max(_cand)
            _rd_tried[_j] = _rd_tried.get(_j, 0) + 1
            _ids = sorted(results[_j].keys())
            _rng = _random.Random(20260612 + 7919 * _rd_tried[_j] + _j)
            _slk = sorted(_ids, key=lambda b: (
                int(blocks[b]["due_date"]) - int(blocks[b]["release_time"])
                - int(blocks[b]["processing_time"]),
                int(blocks[b]["release_time"])))
            _sh = list(_ids)
            _rng.shuffle(_sh)
            _atts = [("fixed", "F1"), ("fixed", "F2"), ("fixed", "F3"),
                     ("fixed", _slk), ("fixed", _sh)]
            _slice = min(_rd_dl, time.monotonic()
                         + max(1.0, 0.5 * (_rd_dl - time.monotonic())))
            _res, _ftd = _decode_attempts(bays[_j], _j, _ids, _atts,
                                          blocks, _slice)
            stats["redecode_tries"] += 1
            if _res is not None and len(_res) == len(_ids):
                _new_td = sum(
                    max(0.0, _res[b]["exit_time"] - blocks[b]["due_date"])
                    for b in _ids)
                if _new_td < _per_tard[_j] - 1e-9:
                    results[_j] = _res
                    stats["redecode_gain"] += _per_tard[_j] - _new_td
                    _log(f"[ff] redecode bay {_j}: tard "
                         f"{_per_tard[_j]:.0f}->{_new_td:.0f}")
        stats["redecode_s"] = round(time.monotonic() - t, 3)
        if stats["redecode_tries"]:
            _log(f"[ff] redecode tries={stats['redecode_tries']} "
                 f"gain={stats['redecode_gain']:.0f} ({stats['redecode_s']}s)")

    # -- 5. assemble + official check --------------------------------------------
    t = time.monotonic()
    flat = []
    per_bay_z1 = {}
    tardy_map = {}
    for j in non_empty:
        z1j = 0.0
        for b, a in results[j].items():
            flat.append(dict(a))
            late = a["exit_time"] - blocks[b]["due_date"]
            z1j += max(0.0, late)
            if late > 1e-9:
                tardy_map[b] = j
        per_bay_z1[j] = round(z1j, 1)
    # Pre-retiming tardy {block: bay} for the caller's ban-feedback loop
    # (OGC_FF_BAN).  Slight overshoot vs post-retiming is fine: banning a
    # block the 5b retime would have fixed just spreads one extra block.
    stats["tardy_map"] = tardy_map
    solution = {"operations": _build_operations(flat)}
    chk = check_feasibility(prob_info, solution)
    stats["check_s"] = round(time.monotonic() - t, 3)
    stats["per_bay_z1"] = per_bay_z1
    stats["feasible"] = bool(chk.get("feasible"))
    if not stats["feasible"]:
        stats["reason"] = f"infeasible stage={chk.get('stage')}"
        stats["total_s"] = round(time.monotonic() - t0, 3)
        return None, stats

    # -- 5b. CP-SAT optimal re-timing of tardy bays (layout fixed -> z2/z3
    # provably unchanged).  Gated through the official checker.
    if chk["obj1"] > 0:
        t = time.monotonic()
        timing_dl = deadline - max(0.5, 2.0 * stats["check_s"])
        if timing_dl - time.monotonic() > 1.0:
            cand = _cpsat_bay_timing_verified(prob_info, bays, results,
                                              deadline=timing_dl)
            if cand is not None:
                chk2 = check_feasibility(prob_info, cand)
                if chk2.get("feasible") and chk2["objective"] < chk["objective"]:
                    stats["z1_pre_timing"] = chk["obj1"]
                    solution, chk = cand, chk2
                    stats["timing_applied"] = True
        stats["timing_s"] = round(time.monotonic() - t, 3)
        _log(f"[ff] retiming applied={stats.get('timing_applied', False)} "
             f"({stats['timing_s']}s) z1 {stats.get('z1_pre_timing', chk['obj1'])}"
             f" -> {chk['obj1']}")

    stats["total_s"] = round(time.monotonic() - t0, 3)
    stats["z1"] = chk["obj1"]
    stats["z2"] = chk["obj2"]
    stats["z3"] = chk["obj3"]
    stats["obj"] = chk["objective"]
    return solution, stats
