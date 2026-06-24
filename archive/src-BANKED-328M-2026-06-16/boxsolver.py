"""OGC 2026 — Grand Shipyard Puzzle — solver entry point (FRESH START).

From-scratch rewrite (2026-06-14 reset). Old solver archived under
`archive/src-full-2026-06-14-reset.zip`. Distilled knowledge + research-driven
hypothesis loop live in `notes/research/INSIGHTS.md` (+ source library
`notes/research/sources.md`, problem facts `notes/FRESH-START-INSIGHTS-2026-06-14.md`).
READ THOSE before extending.

Contract: `algorithm(prob_info, timelimit)` is the eval entry. ALWAYS returns a
solution passing `utils.check_feasibility` (never −1), always inside the wall.

Current method (cycle 1, hypothesis H1):
  * Phase 1 — assignment: each block to its most-preferred bay it fits (z3≈0).
  * Phase 2 — per-bay TIME-EXTENDED 2D PACKING (co-presence): place blocks
    (EDD order) so that any two blocks whose [entry,exit) intervals OVERLAP have
    DISJOINT bounding boxes. bbox-disjoint ⇒ footprints disjoint ⇒ no same-layer
    collision AND no crane j≥k descent-blocking (clear column) ⇒ feasible by
    construction. Each block enters at its release if a free slot exists among the
    co-present blocks, else at the earliest time a co-present block exits (freeing
    space), else serialised. This collapses Z1 vs pure serialisation (the v0 floor)
    while keeping the z3≈0 assignment.
  * Guaranteed fallback: pure per-bay EDD serialisation (always feasible) if the
    packing ever fails or the official check rejects.

Only dependency: `utils` (official, read-only).
"""
from __future__ import annotations

import math
import time

from utils import Bay, Block, check_feasibility


# ---------------------------------------------------------------------------
# Geometry: per-orientation LOCAL bbox of a block (min/max over all layer verts
# at translation (0,0)). World bbox at translation (x,y) = local + (x,y).
# ---------------------------------------------------------------------------

def _orient_bboxes(b, block_data):
    """List over orientations of (minx, miny, maxx, maxy) local bbox, or None for
    orientations with no rasterisable layers. Sorted-by-area handled by caller."""
    out = []
    for oi in range(len(block_data.get("shape", []) or [])):
        try:
            verts = [v for layer in Block(b, block_data, 0, 0, oi).layers_at_pos()
                     for v in layer]
        except Exception:
            verts = []
        if not verts:
            out.append(None); continue
        out.append((min(v[0] for v in verts), min(v[1] for v in verts),
                    max(v[0] for v in verts), max(v[1] for v in verts)))
    return out


_FP_CACHE = {}   # cleared per algorithm() call — block_id indexes are per-instance,
                 # so this MUST NOT persist across instances (cross-instance collision).


def _footprint_cells(b, block_data, oi):
    """Integer cells (ix,iy) the orientation's FOOTPRINT (union of all layers,
    projected to x/y) touches, at translation (0,0). Conservative SUPERSET (a cell
    is included if the polygon intersects its unit square), via Shapely once per
    (block,orient), cached in `_FP_CACHE` (per-instance). Two co-present blocks with
    DISJOINT footprint cells have disjoint footprints ⇒ no shared crane descent
    column ⇒ crane-safe."""
    key = (b, oi)
    c = _FP_CACHE.get(key)
    if c is not None:
        return c
    from shapely.geometry import box as _box
    from shapely.prepared import prep as _prep
    from utils import _poly_from_verts
    layers = Block(b, block_data, 0, 0, oi).layers_at_pos()
    polys = [p for p in (_poly_from_verts(l) for l in layers) if p is not None]
    if not polys:
        _FP_CACHE[key] = (frozenset(), (0, 0, -1, -1)); return _FP_CACHE[key]
    cells = set()
    for p in polys:
        pp = _prep(p)                         # prepared geom: ~10x faster repeats
        x0, y0, x1, y1 = p.bounds
        for ix in range(int(math.floor(x0)), int(math.ceil(x1))):
            for iy in range(int(math.floor(y0)), int(math.ceil(y1))):
                if (ix, iy) in cells:
                    continue
                if pp.intersects(_box(ix, iy, ix + 1, iy + 1)):
                    cells.add((ix, iy))
    cells = frozenset(cells)
    cb = ((min(c[0] for c in cells), min(c[1] for c in cells),
           max(c[0] for c in cells), max(c[1] for c in cells)) if cells else (0, 0, -1, -1))
    _FP_CACHE[key] = (cells, cb)
    return _FP_CACHE[key]


def _bl_fit_cells(b, block_data, oi, copres, W, H):
    """Bottom-left integer translation placing block `b` orientation `oi` so its
    footprint cells are inside [0,W]x[0,H] and cell-DISJOINT from every co-present
    block. `copres` = list of (cells frozenset, cellbox). Candidate translations =
    walls + extreme points (just right of / above each co-present cellbox),
    BL-ordered; first feasible returned. Footprint-disjoint ⇒ crane-safe.
    Returns (x, y, world_cells, world_cellbox) or None."""
    cells, cb = _footprint_cells(b, block_data, oi)
    if not cells:
        return None
    x_lo = -cb[0]; x_hi = (int(W) - 1) - cb[2]
    y_lo = -cb[1]; y_hi = (int(H) - 1) - cb[3]
    if x_hi < x_lo or y_hi < y_lo:
        return None
    occupied = set()
    xs = {x_lo}; ys = {y_lo}
    for (ocells, ocb) in copres:
        occupied |= ocells
        xs.add(ocb[2] + 1 - cb[0])           # B's left just right of O's right
        ys.add(ocb[3] + 1 - cb[1])           # B's bottom just above O's top
    xs = sorted(x for x in xs if x_lo <= x <= x_hi)
    ys = sorted(y for y in ys if y_lo <= y <= y_hi)
    for y in ys:                              # lowest row first (BL)
        for x in xs:                          # then leftmost
            shifted = frozenset((cx + x, cy + y) for (cx, cy) in cells)
            if occupied.isdisjoint(shifted):
                return int(x), int(y), shifted, \
                    (cb[0] + x, cb[1] + y, cb[2] + x, cb[3] + y)
    return None


def _bl_fit(local_bb, copres, W, H):
    """Bottom-left integer translation (x, y) placing the block (local bbox
    `local_bb`) so its WORLD bbox is inside [0,W]x[0,H] and DISJOINT from every
    co-present world bbox in `copres` (list of (x0,y0,x1,y1)). Returns (x, y, wbb)
    or None. Candidate left/bottom edges = walls + right/top edges of co-present
    boxes (the extreme points), BL-ordered."""
    minx, miny, maxx, maxy = local_bb
    bw = maxx - minx; bh = maxy - miny
    if bw > W + 1e-9 or bh > H + 1e-9:
        return None
    # candidate world-left L -> translation x = ceil(L - minx); world-bottom B -> y.
    Ls = {0.0}
    Bs = {0.0}
    for (x0, y0, x1, y1) in copres:
        Ls.add(x1)
        Bs.add(y1)
    xs = sorted({int(math.ceil(L - minx - 1e-9)) for L in Ls})
    ys = sorted({int(math.ceil(B - miny - 1e-9)) for B in Bs})
    cands = []
    for x in xs:
        wx0 = minx + x; wx1 = maxx + x
        if wx0 < -1e-9 or wx1 > W + 1e-9:
            continue
        for y in ys:
            wy0 = miny + y; wy1 = maxy + y
            if wy0 < -1e-9 or wy1 > H + 1e-9:
                continue
            cands.append((wy0, wx0, x, y, (wx0, wy0, wx1, wy1)))
    cands.sort()                                # BL: lowest world-bottom, then left
    for _, _, x, y, wbb in cands:
        ok = True
        for (x0, y0, x1, y1) in copres:
            if not (wbb[2] <= x0 + 1e-9 or x1 <= wbb[0] + 1e-9
                    or wbb[3] <= y0 + 1e-9 or y1 <= wbb[1] + 1e-9):
                ok = False; break          # bbox overlap -> reject
        if ok:
            return x, y, wbb
    return None


def _pack_one_bbox(order, blocks, bay, geo, deadline):
    """Fast time-extended BBOX co-presence packing (co-present blocks bbox-disjoint
    ⇒ crane-safe). Returns (out, tardiness) | (None, inf)."""
    W, H = bay.width, bay.height
    placed = []           # {a, e, wbb}
    out = {}
    tard = 0.0
    for b in order:
        if time.monotonic() >= deadline:
            return None, math.inf
        R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
        D = int(blocks[b]["due_date"])
        oris = sorted((oi for oi, bb in enumerate(geo[b]) if bb is not None),
                      key=lambda oi: (geo[b][oi][2] - geo[b][oi][0])
                      * (geo[b][oi][3] - geo[b][oi][1]))
        if not oris:
            return None, math.inf
        entries = [R] + sorted({p["e"] for p in placed if p["e"] > R})
        chosen = None
        for entry in entries:
            ex = entry + P
            copres = [p["wbb"] for p in placed if p["a"] < ex and entry < p["e"]]
            for oi in oris:
                fit = _bl_fit(geo[b][oi], copres, W, H)
                if fit is not None:
                    chosen = (entry, ex, oi, fit[0], fit[1], fit[2]); break
            if chosen is not None:
                break
        if chosen is None:
            entry = max([R] + [p["e"] for p in placed]); ex = entry + P
            for oi in oris:
                fit = _bl_fit(geo[b][oi], [], W, H)
                if fit is not None:
                    chosen = (entry, ex, oi, fit[0], fit[1], fit[2]); break
            if chosen is None:
                return None, math.inf
        entry, ex, oi, x, y, wbb = chosen
        placed.append({"a": entry, "e": ex, "wbb": wbb})
        out[b] = (int(x), int(y), int(oi), int(entry), int(ex))
        tard += max(0.0, ex - D)
    return out, tard


def _pack_one_cells(order, blocks, bay, deadline):
    """Pack one block order into the bay using time-extended FOOTPRINT-CELL
    co-presence (co-present blocks cell-disjoint ⇒ crane-safe). Denser than bbox.
    Returns (out, tardiness) | (None, inf). out = {block_id:(x,y,oi,entry,exit)}."""
    W, H = bay.width, bay.height
    placed = []           # dicts: {a, e, cells, cb}
    out = {}
    tard = 0.0
    for b in order:
        if time.monotonic() >= deadline:
            return None, math.inf
        R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
        D = int(blocks[b]["due_date"])
        oris = []
        for oi in range(len(blocks[b].get("shape", []) or [])):
            cells, _cb = _footprint_cells(b, blocks[b], oi)
            if cells:
                oris.append((len(cells), oi))
        oris.sort()                                  # densest (fewest cells) first
        oris = [oi for _, oi in oris]
        if not oris:
            return None, math.inf
        entries = [R] + sorted({p["e"] for p in placed if p["e"] > R})
        chosen = None
        for entry in entries:
            ex = entry + P
            copres = [(p["cells"], p["cb"]) for p in placed
                      if p["a"] < ex and entry < p["e"]]
            for oi in oris:
                fit = _bl_fit_cells(b, blocks[b], oi, copres, W, H)
                if fit is not None:
                    chosen = (entry, ex, oi) + fit; break
            if chosen is not None:
                break
        if chosen is None:
            entry = max([R] + [p["e"] for p in placed]); ex = entry + P
            for oi in oris:
                fit = _bl_fit_cells(b, blocks[b], oi, [], W, H)
                if fit is not None:
                    chosen = (entry, ex, oi) + fit; break
            if chosen is None:
                return None, math.inf
        entry, ex, oi, x, y, scells, scb = chosen
        placed.append({"a": entry, "e": ex, "cells": scells, "cb": scb})
        out[b] = (int(x), int(y), int(oi), int(entry), int(ex))
        tard += max(0.0, ex - D)
    return out, tard


def _pack_bay_copresent(members, blocks, bay, deadline, cells=True):
    """Best-of several block ORDERINGS (the packing is order-sensitive; trying
    multiple cheap orders and keeping the lowest-tardiness one cuts residual z1).
    `cells`=False packs bbox-only (fast); True adds dense footprint-cell refine.
    Returns {block_id: (x,y,oi,entry,exit)} or None."""
    geo = {b: _orient_bboxes(b, blocks[b]) for b in members}

    def key_edd(b):     return (int(blocks[b]["due_date"]), int(blocks[b]["release_time"]))
    def key_slack(b):   return (int(blocks[b]["due_date"]) - int(blocks[b]["release_time"])
                                - int(blocks[b]["processing_time"]), int(blocks[b]["due_date"]))
    def key_rel(b):     return (int(blocks[b]["release_time"]), int(blocks[b]["due_date"]))
    def key_proc(b):    return (int(blocks[b]["processing_time"]), int(blocks[b]["due_date"]))
    def key_area(b):    return -min((geo[b][oi][2] - geo[b][oi][0])
                                    * (geo[b][oi][3] - geo[b][oi][1])
                                    for oi, bb in enumerate(geo[b]) if bb is not None)
    orders = [sorted(members, key=k) for k in
              (key_edd, key_slack, key_rel, key_proc, key_area)]

    best, best_t = None, math.inf
    # Fast bbox best-of-orders (always completes — the safety net).
    for order in orders:
        if time.monotonic() >= deadline or best_t <= 0:
            break
        out, t = _pack_one_bbox(order, blocks, bay, geo, deadline)
        if out is not None and t < best_t:
            best, best_t = out, t
    # Dense footprint-cell best-of-orders: only on small-enough bays with budget
    # (cells are Shapely-heavy / O(cells) per op → too slow on big bays). Keeps
    # the lower-tardiness result, so it can only improve on bbox (never regress).
    _cell_max = int(__import__("os").environ.get("OGC_CELL_MAX", "110"))
    if cells and best_t > 0 and len(members) <= _cell_max:
        cell_dl = min(deadline, time.monotonic()
                      + max(2.0, 0.4 * (deadline - time.monotonic())))
        for order in orders:
            if time.monotonic() >= cell_dl or best_t <= 0:
                break
            out, t = _pack_one_cells(order, blocks, bay, cell_dl)
            if out is not None and t < best_t:
                best, best_t = out, t
    return best


def _pack_bay_cpsat(members, blocks, bay, deadline, bay_budget):
    """Per-bay CP-SAT **packing-by-scheduling** [S11,S13,S31,S34]: choose integer
    translations (tx,ty) and entry times e to MINIMISE Σ tardiness, subject to 3D
    (x, y, time) no-overlap — any two blocks whose [entry,exit) intervals overlap
    must have DISJOINT bounding boxes (bbox-disjoint ⇒ footprint-disjoint ⇒ no
    shared crane descent column ⇒ crane-safe by construction, the SAME soundness
    invariant the greedy bbox packer relies on, already validated by the official
    check). Where the greedy packs co-presence online with no backtracking, this
    finds the globally-optimal co-presence schedule the greedy misses — the lever
    for residual z1→0.

    Sound integer encoding despite FLOAT block bboxes: translations are integer,
    so "a's right ≤ b's left" ⇔ maxx_a+tx_a ≤ minx_b+tx_b ⇔ tx_a-tx_b ≤
    floor(minx_b-maxx_a) (integer ≤ float ⇔ integer ≤ floor(float)) — exact, no
    conservatism. Seeded with the greedy layout as a hint (feasible ⇒ CP-SAT can
    only improve this bay) and a guaranteed fallback. Returns the greedy layout on
    any skip/failure/timeout-without-improvement (never breaks correctness; the
    whole spec is obj-gated + check_feasibility-verified downstream).
    Returns {block_id: (x, y, oi, entry, exit)} or None."""
    import os as _os
    # 1. greedy bbox layout = hint + guaranteed fallback.
    L0 = _pack_bay_copresent(members, blocks, bay, deadline, cells=False)
    if L0 is None:
        return None
    m = len(members)
    cmax = int(_os.environ.get("OGC_CPSAT_MAX", "60"))
    if m < 2 or m > cmax or bay_budget < 0.5 or time.monotonic() >= deadline:
        return L0
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return L0

    geo = {b: _orient_bboxes(b, blocks[b]) for b in members}
    W = float(bay.width); H = float(bay.height)
    # Fixed orientation per block = the one greedy chose (keeps the hint valid).
    info = {}
    for b in members:
        x0, y0, oi, e0, _ex0 = L0[b]
        bb = geo[b][oi] if oi < len(geo[b]) else None
        if bb is None:
            return L0
        info[b] = {"minx": bb[0], "miny": bb[1], "maxx": bb[2], "maxy": bb[3],
                   "oi": int(oi), "R": int(blocks[b]["release_time"]),
                   "P": int(blocks[b]["processing_time"]),
                   "D": int(blocks[b]["due_date"]),
                   "x0": int(x0), "y0": int(y0), "e0": int(e0)}
    # Entry horizon: a valid upper bound (co-presence only beats serialisation).
    T_ub = max(info[b]["e0"] for b in members) + max(info[b]["P"] for b in members)

    mdl = cp_model.CpModel()
    tx = {}; ty = {}; ev = {}; tard = []
    for b in members:
        I = info[b]
        txlo = int(math.ceil(-I["minx"] - 1e-9)); txhi = int(math.floor(W - I["maxx"] + 1e-9))
        tylo = int(math.ceil(-I["miny"] - 1e-9)); tyhi = int(math.floor(H - I["maxy"] + 1e-9))
        if txhi < txlo or tyhi < tylo:
            return L0
        tx[b] = mdl.NewIntVar(txlo, txhi, "")
        ty[b] = mdl.NewIntVar(tylo, tyhi, "")
        ev[b] = mdl.NewIntVar(I["R"], int(T_ub), "")
        td = mdl.NewIntVar(0, int(T_ub) + I["P"], "")
        mdl.Add(td >= ev[b] + I["P"] - I["D"])
        tard.append(td)
        mdl.AddHint(tx[b], min(max(I["x0"], txlo), txhi))
        mdl.AddHint(ty[b], min(max(I["y0"], tylo), tyhi))
        mdl.AddHint(ev[b], min(max(I["e0"], I["R"]), int(T_ub)))
    mem = list(members)
    for i in range(len(mem)):
        a = mem[i]; Ia = info[a]
        for k in range(i + 1, len(mem)):
            c = mem[k]; Ic = info[c]
            aL = mdl.NewBoolVar(""); cL = mdl.NewBoolVar("")
            aD = mdl.NewBoolVar(""); cD = mdl.NewBoolVar("")
            aT = mdl.NewBoolVar(""); cT = mdl.NewBoolVar("")
            mdl.Add(tx[a] - tx[c] <= int(math.floor(Ic["minx"] - Ia["maxx"]))).OnlyEnforceIf(aL)
            mdl.Add(tx[c] - tx[a] <= int(math.floor(Ia["minx"] - Ic["maxx"]))).OnlyEnforceIf(cL)
            mdl.Add(ty[a] - ty[c] <= int(math.floor(Ic["miny"] - Ia["maxy"]))).OnlyEnforceIf(aD)
            mdl.Add(ty[c] - ty[a] <= int(math.floor(Ia["miny"] - Ic["maxy"]))).OnlyEnforceIf(cD)
            mdl.Add(ev[a] - ev[c] <= -Ia["P"]).OnlyEnforceIf(aT)
            mdl.Add(ev[c] - ev[a] <= -Ic["P"]).OnlyEnforceIf(cT)
            mdl.AddBoolOr([aL, cL, aD, cD, aT, cT])
    mdl.Minimize(sum(tard))

    solver = cp_model.CpSolver()
    budget = min(float(bay_budget), deadline - time.monotonic())
    if budget < 0.5:
        return L0
    solver.parameters.max_time_in_seconds = float(budget)
    solver.parameters.num_search_workers = int(_os.environ.get("OGC_BD_WORKERS", "1"))
    solver.parameters.random_seed = 1            # determinism (1 worker; >1 ⇒ dedicated) (CP-SAT variance guard)
    try:
        st = solver.Solve(mdl)
    except Exception:
        return L0
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return L0
    out = {}
    try:
        for b in members:
            xv = int(solver.Value(tx[b])); yv = int(solver.Value(ty[b]))
            e = int(solver.Value(ev[b]))
            out[b] = (xv, yv, info[b]["oi"], e, e + info[b]["P"])
    except Exception:
        return L0

    def _tard(layout):
        return sum(max(0, layout[b][4] - info[b]["D"]) for b in members)
    return out if _tard(out) <= _tard(L0) else L0


def _cell_rects(cells, cb, kmax):
    """Cover the footprint `cells` (set of int (x,y)) with ≤ kmax axis-aligned
    rectangles, returned as inclusive cell coords (x0,y0,x1,y1). Exact disjoint
    partition via greedy row-merged maximal rectangles; if it needs > kmax, greedily
    merge the least-area-wasteful pair down to kmax (then a COVER ⊇ footprint, may
    include a few empty cells — still a sound superset, so cross-block rect-pair
    disjointness ⇒ cell-set disjoint ⇒ footprint-disjoint ⇒ crane-safe). kmax≤1 ⇒
    the single bounding box `cb` (= _pack_bay_cpsat's conservatism)."""
    if kmax <= 1 or not cells:
        return [tuple(cb)]
    remaining = set(cells)
    rects = []
    while remaining:
        x0, y0 = min(remaining, key=lambda c: (c[1], c[0]))
        x1 = x0
        while (x1 + 1, y0) in remaining:
            x1 += 1
        y1 = y0
        while all((x, y1 + 1) in remaining for x in range(x0, x1 + 1)):
            y1 += 1
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                remaining.discard((x, y))
        rects.append((x0, y0, x1, y1))
    while len(rects) > kmax:                       # merge least-wasteful pair
        best = None
        for i in range(len(rects)):
            a = rects[i]
            for j in range(i + 1, len(rects)):
                b = rects[j]
                mb = (min(a[0], b[0]), min(a[1], b[1]),
                      max(a[2], b[2]), max(a[3], b[3]))
                added = ((mb[2] - mb[0] + 1) * (mb[3] - mb[1] + 1)
                         - (a[2] - a[0] + 1) * (a[3] - a[1] + 1)
                         - (b[2] - b[0] + 1) * (b[3] - b[1] + 1))
                if best is None or added < best[0]:
                    best = (added, i, j, mb)
        _, i, j, mb = best
        rects = [r for k, r in enumerate(rects) if k != i and k != j] + [mb]
    return rects


def _pack_bay_boxdecomp(members, blocks, bay, deadline, bay_budget):
    """Box-DECOMPOSITION CP-SAT packing-by-scheduling — the cycle-13 lever for the
    REALIZE gap (z1 floors at 76–1411 at preferred where area says z1≈0 is feasible;
    `notes/research/_whyhard.py`/`_prefpack.py`). Generalises `_pack_bay_cpsat`:
    each block's single LOOSE bbox is replaced by a ≤K-rectangle COVER of its
    footprint CELLS (the same tight crane-safe geometry the greedy `cells` packer
    uses). Co-present blocks must have EVERY rect-pair disjoint ⇒ cell-set disjoint ⇒
    footprint-disjoint ⇒ crane-safe — but far tighter than single-bbox, so CP-SAT can
    realise the dense co-presence the greedy BL search misses. Seeded with the greedy
    cells layout (a valid hint when the cover is exact); greedy fallback on any skip/
    failure/no-improvement ⇒ never breaks correctness (obj-gated + check downstream).
    Returns {block_id: (x, y, oi, entry, exit)} or None."""
    import os as _os
    L0 = _pack_bay_copresent(members, blocks, bay, deadline, cells=True)
    if L0 is None:
        return None
    m = len(members)
    cmax = int(_os.environ.get("OGC_BOXDECOMP_MAX", "70"))
    K = int(_os.environ.get("OGC_BOXDECOMP_K", "2"))   # K=2 beats single-bbox; K=3
    #   backfires (9× model, CP-SAT can't solve it in budget) — see INSIGHTS cyc13.
    if m < 2 or m > cmax or bay_budget < 0.5 or time.monotonic() >= deadline:
        return L0
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return L0
    from shapely.ops import unary_union as _unary_union
    from utils import _poly_from_verts
    W = int(bay.width); H = int(bay.height)
    info = {}; rects = {}; fp_area = {}
    for b in members:
        x0, y0, oi, e0, _ex0 = L0[b]
        cells, cb = _footprint_cells(b, blocks[b], oi)
        if not cells:
            return L0
        txlo = -cb[0]; txhi = (W - 1) - cb[2]
        tylo = -cb[1]; tyhi = (H - 1) - cb[3]
        if txhi < txlo or tyhi < tylo:
            return L0
        rects[b] = _cell_rects(cells, cb, K)
        # TRUE footprint area (Shapely union of layers) — a VALID demand for the
        # redundant area-cumulative (≤ #cells, never over-estimates ⇒ never cuts a
        # feasible layout). floor ⇒ Σ demand ≤ Σ area ≤ bay area = capacity.
        _pl = [p for p in (_poly_from_verts(l)
                           for l in Block(b, blocks[b], 0, 0, oi).layers_at_pos())
               if p is not None]
        fp_area[b] = max(1, int(_unary_union(_pl).area)) if _pl else 1
        info[b] = {"oi": int(oi), "R": int(blocks[b]["release_time"]),
                   "P": int(blocks[b]["processing_time"]),
                   "D": int(blocks[b]["due_date"]),
                   "x0": int(x0), "y0": int(y0), "e0": int(e0),
                   "txlo": txlo, "txhi": txhi, "tylo": tylo, "tyhi": tyhi}
    mem = list(members)
    npairs = 0                                     # model-size guard (build cost)
    for i in range(len(mem)):
        for k in range(i + 1, len(mem)):
            npairs += len(rects[mem[i]]) * len(rects[mem[k]])
    if npairs > int(_os.environ.get("OGC_BOXDECOMP_CAP", "90000")):
        return L0
    T_ub = max(info[b]["e0"] for b in members) + max(info[b]["P"] for b in members)

    mdl = cp_model.CpModel()
    tx = {}; ty = {}; ev = {}; tard = []
    for b in members:
        I = info[b]
        tx[b] = mdl.NewIntVar(I["txlo"], I["txhi"], "")
        ty[b] = mdl.NewIntVar(I["tylo"], I["tyhi"], "")
        ev[b] = mdl.NewIntVar(I["R"], int(T_ub), "")
        td = mdl.NewIntVar(0, int(T_ub) + I["P"], "")
        mdl.Add(td >= ev[b] + I["P"] - I["D"])
        tard.append(td)
        mdl.AddHint(tx[b], min(max(I["x0"], I["txlo"]), I["txhi"]))
        mdl.AddHint(ty[b], min(max(I["y0"], I["tylo"]), I["tyhi"]))
        mdl.AddHint(ev[b], min(max(I["e0"], I["R"]), int(T_ub)))
    # ★ Cycle 17: REDUNDANT area-cumulative. Co-present blocks have disjoint
    # footprints ⊆ bay ⇒ at every instant Σ footprint_area ≤ bay area. Implied by the
    # pairwise no-overlap but, as an explicit cumulative, CP-SAT's strong cumulative/
    # energetic propagator prunes the schedule space the weak pairwise-disjunctive LP
    # relaxation leaves open ⇒ drives z1 toward the energetic-feasible floor.
    if _os.environ.get("OGC_BD_CUMUL", "1").strip().lower() not in ("0", "false", "no", "off"):
        cap = max(1, W * H)
        ivs = []; dems = []
        for b in members:
            iv = mdl.NewIntervalVar(ev[b], info[b]["P"], ev[b] + info[b]["P"], "")
            ivs.append(iv); dems.append(min(fp_area[b], cap))
        if ivs:
            mdl.AddCumulative(ivs, dems, cap)
    for i in range(len(mem)):
        a = mem[i]; Pa = info[a]["P"]
        for k in range(i + 1, len(mem)):
            c = mem[k]; Pc = info[c]["P"]
            aT = mdl.NewBoolVar(""); cT = mdl.NewBoolVar("")
            mdl.Add(ev[a] - ev[c] <= -Pa).OnlyEnforceIf(aT)
            mdl.Add(ev[c] - ev[a] <= -Pc).OnlyEnforceIf(cT)
            for (rax0, ray0, rax1, ray1) in rects[a]:
                for (rcx0, rcy0, rcx1, rcy1) in rects[c]:
                    aL = mdl.NewBoolVar(""); cL = mdl.NewBoolVar("")
                    aD = mdl.NewBoolVar(""); cD = mdl.NewBoolVar("")
                    mdl.Add(tx[a] - tx[c] <= rcx0 - rax1 - 1).OnlyEnforceIf(aL)
                    mdl.Add(tx[c] - tx[a] <= rax0 - rcx1 - 1).OnlyEnforceIf(cL)
                    mdl.Add(ty[a] - ty[c] <= rcy0 - ray1 - 1).OnlyEnforceIf(aD)
                    mdl.Add(ty[c] - ty[a] <= ray0 - rcy1 - 1).OnlyEnforceIf(cD)
                    mdl.AddBoolOr([aL, cL, aD, cD, aT, cT])
    # ★ Cycle 17: z1=0 FEASIBILITY mode. CP-SAT solves feasibility far better than it
    # minimises tardiness — force every exit ≤ due (z1=0) and search for ANY feasible
    # crane-safe schedule. SAT ⇒ the realize gap is CRACKED at this assignment (obj
    # collapses to ~z2). UNSAT/timeout ⇒ fall through to minimise-tardiness (the
    # cumulative-strengthened model still drives z1 down). Two-phase, both obj-gated.
    _z1zero = _os.environ.get("OGC_BD_Z1ZERO", "0").strip().lower() not in (
        "0", "false", "no", "off")
    if _z1zero:
        z1z = cp_model.CpModel()
        z1z.proto.CopyFrom(mdl.proto)            # clone constraints; var indices match
        for b in members:
            z1z.Add(ev[b] + info[b]["P"] <= info[b]["D"])
        _s = cp_model.CpSolver()
        _b = min(float(bay_budget), deadline - time.monotonic())
        if _b >= 0.5:
            _s.parameters.max_time_in_seconds = float(_b)
            _s.parameters.num_search_workers = 1
            _s.parameters.random_seed = 1
            try:
                if _s.Solve(z1z) in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    out = {}
                    for b in members:
                        e = int(_s.Value(ev[b]))
                        out[b] = (int(_s.Value(tx[b])), int(_s.Value(ty[b])),
                                  info[b]["oi"], e, e + info[b]["P"])
                    return out                       # z1=0 realised ⇒ huge win
            except Exception:
                pass
    mdl.Minimize(sum(tard))

    solver = cp_model.CpSolver()
    budget = min(float(bay_budget), deadline - time.monotonic())
    if budget < 0.5:
        return L0
    solver.parameters.max_time_in_seconds = float(budget)
    solver.parameters.num_search_workers = int(_os.environ.get("OGC_BD_WORKERS", "1"))
    solver.parameters.random_seed = 1            # determinism (1 worker; >1 ⇒ dedicated)
    try:
        st = solver.Solve(mdl)
    except Exception:
        return L0
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return L0
    out = {}
    try:
        for b in members:
            xv = int(solver.Value(tx[b])); yv = int(solver.Value(ty[b]))
            e = int(solver.Value(ev[b]))
            out[b] = (xv, yv, info[b]["oi"], e, e + info[b]["P"])
    except Exception:
        return L0

    def _tard(layout):
        return sum(max(0, layout[b][4] - info[b]["D"]) for b in members)
    return out if _tard(out) <= _tard(L0) else L0


def _pack_bay_lns(members, blocks, bay, deadline):
    """Cycle-14 per-bay RUIN-AND-RECREATE realize engine — escapes the greedy-BL AND
    CP-SAT-pairwise z1 ceilings (both floor z1 ≫ the energetic-feasible 0; INSIGHTS
    cyc13). Start from the greedy cells layout; repeatedly RUIN a temporal cluster of
    blocks and RECREATE them by best-insertion over (orientation × entry-time × BL
    cell-position), accepting any layout that lowers total tardiness. Two levers the
    CP-SAT packers lack: (1) ORIENTATION freedom per re-insertion, (2) accurate cells
    decode (not the bbox proxy). Crane-safe by cells-disjoint co-presence (same
    invariant as the cells packer) + the official check downstream. Deterministic
    (fixed RNG). obj-gated ⇒ never regresses below the greedy cells floor.
    Returns {block_id: (x, y, oi, entry, exit)} or None."""
    import os as _os
    import random as _random
    L0 = _pack_bay_copresent(members, blocks, bay, deadline, cells=True)
    if L0 is None:
        return None
    m = len(members)
    if m < 2 or time.monotonic() >= deadline:
        return L0
    W = int(bay.width); H = int(bay.height)
    P = {b: int(blocks[b]["processing_time"]) for b in members}
    R = {b: int(blocks[b]["release_time"]) for b in members}
    D = {b: int(blocks[b]["due_date"]) for b in members}
    n_or = {b: len(blocks[b].get("shape", []) or []) for b in members}
    mem = list(members)
    # speed knobs: orientation freedom is 4× the inner cost for uncertain gain — try
    # only the L0 orientation by default (OGC_LNS_ORIENT=1 to try all); bound the
    # candidate-entry scan so a congested bay can't make one insertion O(n²).
    try_all_or = _os.environ.get("OGC_LNS_ORIENT", "0").strip().lower() not in (
        "0", "false", "no", "off")
    TSCAN = int(_os.environ.get("OGC_LNS_TSCAN", "16"))
    oi0 = {b: int(L0[b][2]) for b in members}

    def hydrate(L):
        out = {}
        for b in members:
            x, y, oi, e, ex = L[b]
            cells, cb = _footprint_cells(b, blocks[b], oi)
            wc = frozenset((cx + x, cy + y) for (cx, cy) in cells)
            wcb = (cb[0] + x, cb[1] + y, cb[2] + x, cb[3] + y)
            out[b] = (x, y, oi, e, ex, wc, wcb)
        return out

    def best_insert(b, items):
        """Min-tardiness (orientation, entry, BL cell-pos) for b given placed
        `items` (list of (x,y,oi,e,ex,wc,wcb)). Returns the 7-tuple, or None."""
        best = None; best_key = None
        oris = range(n_or[b]) if try_all_or else (oi0[b],)
        rb = R[b]
        # candidate entry times: release + the nearest TSCAN free-events (exits) after
        # it, ascending, + a guaranteed-feasible serialise time (max exit).
        exits = sorted({it[4] for it in items if it[4] > rb})
        ts = [rb] + exits[:TSCAN]
        maxex = exits[-1] if exits else rb
        if maxex not in ts:
            ts.append(maxex)
        for oi in oris:
            cells, _cb = _footprint_cells(b, blocks[b], oi)
            if not cells:
                continue
            for t in ts:
                te = t + P[b]
                copres = [(it[5], it[6]) for it in items if it[3] < te and it[4] > t]
                fit = _bl_fit_cells(b, blocks[b], oi, copres, W, H)
                if fit is not None:
                    x, y, wc, wcb = fit
                    key = (max(0, te - D[b]), t)
                    if best_key is None or key < best_key:
                        best_key = key
                        best = (x, y, oi, t, te, wc, wcb)
                    break                        # earliest feasible t = min tardiness
        return best

    def z1_of(L):
        return sum(max(0, L[b][4] - D[b]) for b in members)

    cur = hydrate(L0)
    best = dict(cur); best_z1 = z1_of(cur)
    if best_z1 <= 0:
        return L0
    rng = _random.Random(1)
    K = max(2, min(8, m // 6))
    last_check = 0
    it_n = 0
    while True:
        it_n += 1
        if (it_n & 7) == 0 and time.monotonic() >= deadline:
            break
        tardy = [b for b in mem if cur[b][4] > D[b]]
        seed = (rng.choice(tardy) if (tardy and rng.random() < 0.85)
                else rng.choice(mem))
        se, sx = cur[seed][3], cur[seed][4]
        related = sorted(mem, key=lambda b: abs(cur[b][3] - se) + abs(cur[b][4] - sx))
        victims = set(related[:K])
        partial = {b: cur[b] for b in mem if b not in victims}
        ok = True
        for b in sorted(victims, key=lambda b: (D[b], R[b])):
            ins = best_insert(b, list(partial.values()))
            if ins is None:
                ok = False
                break
            partial[b] = ins
        if not ok:
            continue
        z1 = z1_of(partial)
        if z1 <= best_z1:                        # accept equal (drift) + improving
            cur = partial
            if z1 < best_z1:
                best = dict(partial); best_z1 = z1
                if best_z1 <= 0:
                    break
    return {b: (best[b][0], best[b][1], best[b][2], best[b][3], best[b][4])
            for b in members}


# ---------------------------------------------------------------------------
# CYCLE 9 — CRANE-OVERLAP co-presence (the differentiated lever).
# bbox/cell-disjoint packing is CONSERVATIVE: it forbids ALL footprint overlap.
# The TRUE crane rule (j≥k) only forbids new-block layer k from hitting an
# existing block's layer j≥k — so a block's UPPER layers may OVERHANG another
# block's LOWER layers (diagnostic: 11–28% of set1 multi-layer blocks overhang).
# We pack with the per-layer j≥k entry rule (denser than cells) and then VALIDATE
# the whole bay with the OFFICIAL check_entry/check_exit (catches exit-order
# overhang violations); on any failure we fall back to the cells layout, so the
# spec is correct-by-construction and obj-gated ⇒ never regresses.
# ---------------------------------------------------------------------------

_LAYER_CACHE = {}    # (b,oi) -> (per:list[frozenset], upper:list[frozenset], cb)
                     # cleared per algorithm() call (block_id keys are per-instance)


def _layer_cells(b, block_data, oi):
    """Per-LAYER integer footprint cells at translation (0,0), plus the upper-
    prefix unions `upper[k] = ∪_{j≥k} layer_j` (so upper[0] = full footprint) and
    the full-footprint cellbox. The j≥k crane rule wants new-layer-k vs existing
    layers≥k → that is exactly `upper[k]`. Cached in `_LAYER_CACHE` (per-instance)."""
    key = (b, oi)
    c = _LAYER_CACHE.get(key)
    if c is not None:
        return c
    from shapely.geometry import box as _box
    from shapely.prepared import prep as _prep
    from utils import _poly_from_verts
    layers = Block(b, block_data, 0, 0, oi).layers_at_pos()
    per = []
    for l in layers:
        p = _poly_from_verts(l)
        if p is None:
            per.append(frozenset()); continue
        s = set(); pp = _prep(p); x0, y0, x1, y1 = p.bounds
        for ix in range(int(math.floor(x0)), int(math.ceil(x1))):
            for iy in range(int(math.floor(y0)), int(math.ceil(y1))):
                if pp.intersects(_box(ix, iy, ix + 1, iy + 1)):
                    s.add((ix, iy))
        per.append(frozenset(s))
    nl = len(per)
    upper = [frozenset().union(*per[k:]) if per[k:] else frozenset() for k in range(nl)]
    allc = upper[0] if upper else frozenset()
    cb = ((min(c[0] for c in allc), min(c[1] for c in allc),
           max(c[0] for c in allc), max(c[1] for c in allc)) if allc else (0, 0, -1, -1))
    _LAYER_CACHE[key] = (per, upper, cb)
    return _LAYER_CACHE[key]


def _bl_fit_crane(b, block_data, oi, occ_upper, occ_boxes, W, H):
    """BL translation placing block `b` so the per-layer j≥k crane ENTRY rule holds
    vs the co-present set: for every layer k, the block's layer-k cells must be
    disjoint from `occ_upper[k]` = ∪ (co-present blocks' cells at layers ≥ k). This
    ALLOWS the block's upper layers to sit over co-present lower layers (overhang),
    which cells/bbox forbid. Returns (x, y, shifted_upper_list, world_cb) or None."""
    per, upper, cb = _layer_cells(b, block_data, oi)
    if not upper or not upper[0]:
        return None
    x_lo = -cb[0]; x_hi = (int(W) - 1) - cb[2]
    y_lo = -cb[1]; y_hi = (int(H) - 1) - cb[3]
    if x_hi < x_lo or y_hi < y_lo:
        return None
    # Base (layer-0) cellbox: candidates placing the BASE just past a neighbour's
    # footprint let the block's OVERHANG reach back over that neighbour (the whole
    # point of the crane rule) — full-cb candidates alone never exploit overhang.
    base = per[0] if per else frozenset()
    if base:
        bx0 = min(c[0] for c in base); by0 = min(c[1] for c in base)
        bx1 = max(c[0] for c in base); by1 = max(c[1] for c in base)
    else:
        bx0, by0, bx1, by1 = cb
    xs = {x_lo}; ys = {y_lo}
    for ob in occ_boxes:
        xs.add(ob[2] + 1 - cb[0]); ys.add(ob[3] + 1 - cb[1])    # full-box adjacency
        xs.add(ob[2] + 1 - bx0); ys.add(ob[3] + 1 - by0)        # base just past neighbour
        xs.add(ob[0] - 1 - bx1); ys.add(ob[1] - 1 - by1)        # base just before neighbour
    xs = sorted(x for x in xs if x_lo <= x <= x_hi)
    ys = sorted(y for y in ys if y_lo <= y <= y_hi)
    nl = len(per)
    for y in ys:
        for x in xs:
            ok = True
            for k in range(nl):
                occ = occ_upper.get(k)
                if not occ or not per[k]:
                    continue
                shifted = frozenset((cx + x, cy + y) for (cx, cy) in per[k])
                if not occ.isdisjoint(shifted):
                    ok = False; break
            if ok:
                up_sh = [frozenset((cx + x, cy + y) for (cx, cy) in upper[k])
                         for k in range(nl)]
                return int(x), int(y), up_sh, (cb[0] + x, cb[1] + y, cb[2] + x, cb[3] + y)
    return None


def _pack_one_crane(order, blocks, bay, deadline):
    """Greedy time-extended crane-overlap packing (per-layer j≥k entry rule).
    Returns (out, tardiness) | (None, inf). NOT yet validated for exit-order —
    the caller validates via `_bay_crane_ok` and falls back to cells on failure."""
    W, H = bay.width, bay.height
    placed = []        # {a, e, up:list[frozenset], cb}
    out = {}
    tard = 0.0
    for b in order:
        if time.monotonic() >= deadline:
            return None, math.inf
        R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
        D = int(blocks[b]["due_date"])
        oris = []
        for oi in range(len(blocks[b].get("shape", []) or [])):
            per, upper, _cb = _layer_cells(b, blocks[b], oi)
            if upper and upper[0]:
                oris.append((len(per[0]) if per else 0, oi))
        oris.sort()
        oris = [oi for _, oi in oris]
        if not oris:
            return None, math.inf
        entries = [R] + sorted({p["e"] for p in placed if p["e"] > R})
        chosen = None
        for entry in entries:
            ex = entry + P
            occ_up = {}; occ_boxes = []
            for p in placed:
                if p["a"] < ex and entry < p["e"]:
                    occ_boxes.append(p["cb"])
                    for k, cells in enumerate(p["up"]):
                        if cells:
                            occ_up[k] = occ_up.get(k, frozenset()) | cells
            for oi in oris:
                fit = _bl_fit_crane(b, blocks[b], oi, occ_up, occ_boxes, W, H)
                if fit is not None:
                    chosen = (entry, ex, oi) + fit; break
            if chosen is not None:
                break
        if chosen is None:
            entry = max([R] + [p["e"] for p in placed]); ex = entry + P
            for oi in oris:
                fit = _bl_fit_crane(b, blocks[b], oi, {}, [], W, H)
                if fit is not None:
                    chosen = (entry, ex, oi) + fit; break
            if chosen is None:
                return None, math.inf
        entry, ex, oi, x, y, up_sh, cbw = chosen
        placed.append({"a": entry, "e": ex, "up": up_sh, "cb": cbw})
        out[b] = (int(x), int(y), int(oi), int(entry), int(ex))
        tard += max(0.0, ex - D)
    return out, tard


def _bay_crane_ok(out, blocks, bay):
    """Validate a bay layout+schedule with the OFFICIAL crane predicates: simulate
    entry/exit events in time order (exit before entry at equal time, per checker
    Stage 5); every check_entry / check_exit must be obstruction-free. This catches
    exit-order overhang violations the greedy entry rule alone can't see."""
    from utils import check_entry, check_exit
    objs = {}
    events = []
    for b, (x, y, oi, en, ex) in out.items():
        objs[b] = Block(b, blocks[b], int(x), int(y), int(oi))
        events.append((en, 1, b))   # 1 = entry
        events.append((ex, 0, b))   # 0 = exit (sorts before entry at equal time)
    events.sort(key=lambda e: (e[0], e[1]))
    present = {}
    for _t, kind, b in events:
        if kind == 0:               # exit
            if check_exit(bay, list(present.values()), objs[b], fast=True):
                return False
            present.pop(b, None)
        else:                        # entry
            if check_entry(bay, list(present.values()), objs[b], fast=True):
                return False
            present[b] = objs[b]
    return True


def _pack_bay_crane(members, blocks, bay, deadline):
    """Best-of-orders crane-overlap pack, validated by the official predicates;
    falls back to the (always-valid) cells pack on any failure. Returns the lower-
    tardiness of {validated crane, cells} ⇒ crane can only help, never regress."""
    import os as _os
    cmax = int(_os.environ.get("OGC_CRANE_MAX", "110"))
    cells = _pack_bay_copresent(members, blocks, bay, deadline, cells=True)
    if len(members) < 2 or len(members) > cmax:
        return cells

    def k_edd(b):   return (int(blocks[b]["due_date"]), int(blocks[b]["release_time"]))
    def k_slack(b): return (int(blocks[b]["due_date"]) - int(blocks[b]["release_time"])
                            - int(blocks[b]["processing_time"]), int(blocks[b]["due_date"]))
    def k_rel(b):   return (int(blocks[b]["release_time"]), int(blocks[b]["due_date"]))
    orders = [sorted(members, key=k) for k in (k_edd, k_slack, k_rel)]

    best, best_t = None, math.inf
    for order in orders:
        if time.monotonic() >= deadline or best_t <= 0:
            break
        out, t = _pack_one_crane(order, blocks, bay, deadline)
        if out is not None and t < best_t and _bay_crane_ok(out, blocks, bay):
            best, best_t = out, t
    if best is None:
        return cells
    if cells is not None:
        ct = sum(max(0, cells[b][4] - int(blocks[b]["due_date"])) for b in members)
        if ct < best_t:
            return cells
    return best


# ---------------------------------------------------------------------------
# Fallback: per-block bottom-left fit + pure EDD serialisation (always feasible).
# ---------------------------------------------------------------------------

def _fit_position(b, block_data, bay, oi):
    probe = Block(b, block_data, 0, 0, oi)
    verts = [v for layer in probe.layers_at_pos() for v in layer]
    if not verts:
        return None
    minx = min(v[0] for v in verts); maxx = max(v[0] for v in verts)
    miny = min(v[1] for v in verts); maxy = max(v[1] for v in verts)
    x_lo = int(math.ceil(-minx - 1e-9)); x_hi = int(math.floor(bay.width - maxx + 1e-9))
    y_lo = int(math.ceil(-miny - 1e-9)); y_hi = int(math.floor(bay.height - maxy + 1e-9))
    if x_hi < x_lo or y_hi < y_lo:
        return None
    for x in (x_lo, x_lo + 1, x_hi):
        for y in (y_lo, y_lo + 1, y_hi):
            if x_lo <= x <= x_hi and y_lo <= y <= y_hi and \
                    bay.contains_block(Block(b, block_data, int(x), int(y), oi)):
                return int(x), int(y)
    return None


def _fits_per_bay(b, block_data, bays):
    """{bay_idx: (orient, x, y)} first fitting placement per bay (cached input)."""
    fits = {}
    for j in range(len(bays)):
        for oi in range(len(block_data.get("shape", []) or [])):
            pos = _fit_position(b, block_data, bays[j], oi)
            if pos is not None:
                fits[j] = (oi, pos[0], pos[1]); break
    return fits


def _area_time(b, block_data):
    """Min-orientation bbox area × processing time = area-time demand."""
    best = None
    for oi in range(len(block_data.get("shape", []) or [])):
        verts = [v for layer in Block(b, block_data, 0, 0, oi).layers_at_pos()
                 for v in layer]
        if verts:
            a = (max(v[0] for v in verts) - min(v[0] for v in verts)) * \
                (max(v[1] for v in verts) - min(v[1] for v in verts))
            best = a if best is None else min(best, a)
    return (best or 1.0) * int(block_data["processing_time"])


def _assign_preferred(blocks, bays):
    """Each block to the most-preferred bay it fits (z3≈0)."""
    n, nb = len(blocks), len(bays)
    placements, members = {}, [[] for _ in range(nb)]
    for b in range(n):
        bd = blocks[b]
        prefs = bd.get("bay_preferences", [0.0] * nb)
        fits = _fits_per_bay(b, bd, bays)
        if fits:
            j = max(fits, key=lambda k: prefs[k])
            got = (j,) + fits[j]
        else:
            got = (0, 0, 0, 0)
        placements[b] = got
        members[got[0]].append(b)
    return placements, members


def _assign_balanced(blocks, bays):
    """Balance area-time load across bays (reduces per-bay congestion ⇒ z1),
    accepting preference deviation (z3) — net-positive when w1 ≫ w3. Largest-demand
    block first to the fitting bay with the lowest projected load ratio (pref
    tie-break)."""
    n, nb = len(blocks), len(bays)
    cap = [max(1.0, bays[j].width * bays[j].height) for j in range(nb)]
    load = [0.0] * nb
    placements, members = {}, [[] for _ in range(nb)]
    dem = {b: _area_time(b, blocks[b]) for b in range(n)}
    fits_all = {b: _fits_per_bay(b, blocks[b], bays) for b in range(n)}
    for b in sorted(range(n), key=lambda b: -dem[b]):
        bd = blocks[b]
        prefs = bd.get("bay_preferences", [0.0] * nb)
        fits = fits_all[b]
        if fits:
            j = min(fits, key=lambda k: ((load[k] + dem[b]) / cap[k], -prefs[k]))
            got = (j,) + fits[j]
        else:
            got = (0, 0, 0, 0)
        placements[b] = got
        members[got[0]].append(b)
        load[got[0]] += dem[b]
    return placements, members


def _assign_capped(blocks, bays, alpha):
    """Spectrum between preferred (z3≈0) and balanced: keep each block in its most-
    preferred FEASIBLE bay until that bay's projected area-time load exceeds
    alpha·capacity, then spill to the next-preferred bay still under cap (least-
    loaded if all are over). alpha=∞ ≈ preferred; small alpha ≈ balanced. Largest-
    demand block first."""
    n, nb = len(blocks), len(bays)
    cap = [max(1.0, bays[j].width * bays[j].height) for j in range(nb)]
    load = [0.0] * nb
    placements, members = {}, [[] for _ in range(nb)]
    dem = {b: _area_time(b, blocks[b]) for b in range(n)}
    fits_all = {b: _fits_per_bay(b, blocks[b], bays) for b in range(n)}
    for b in sorted(range(n), key=lambda b: -dem[b]):
        prefs = blocks[b].get("bay_preferences", [0.0] * nb)
        fits = fits_all[b]
        if fits:
            by_pref = sorted(fits, key=lambda k: -prefs[k])
            under = [k for k in by_pref if (load[k] + dem[b]) <= alpha * cap[k]]
            j = under[0] if under else min(fits, key=lambda k: (load[k] + dem[b]) / cap[k])
            got = (j,) + fits[j]
        else:
            got = (0, 0, 0, 0)
        placements[b] = got
        members[got[0]].append(b)
        load[got[0]] += dem[b]
    return placements, members


def _pack_all(members, placements, bays, blocks, deadline, mode="bbox"):
    """Pack every non-empty bay (co-presence). Mutates `placements` with the
    packer's chosen orient/pos. `mode` ∈ {"bbox","cells","cpsat"}. For "cpsat"
    the remaining wall budget is split evenly across non-empty bays (a fast bay
    donates its leftover to later bays). Returns timing {b:(entry,exit)} or None."""
    pack_timed = {}
    nonempty = [j for j, mem in enumerate(members) if mem]
    for idx, j in enumerate(nonempty):
        mem = members[j]
        if mode in ("cpsat", "boxdecomp"):
            remaining_bays = len(nonempty) - idx
            budget = (deadline - time.monotonic()) / max(1, remaining_bays)
            packer = _pack_bay_boxdecomp if mode == "boxdecomp" else _pack_bay_cpsat
            res = packer(mem, blocks, bays[j], deadline, budget)
        elif mode == "lns":
            remaining_bays = len(nonempty) - idx
            sub_dl = time.monotonic() + (deadline - time.monotonic()) / max(1, remaining_bays)
            res = _pack_bay_lns(mem, blocks, bays[j], min(deadline, sub_dl))
        elif mode == "crane":
            res = _pack_bay_crane(mem, blocks, bays[j], deadline)
        else:
            res = _pack_bay_copresent(mem, blocks, bays[j], deadline,
                                      cells=(mode == "cells"))
        if res is None:
            return None
        for b, (x, y, oi, entry, ex) in res.items():
            placements[b] = (j, oi, x, y)
            pack_timed[b] = (entry, ex)
    return pack_timed


def _solve_reassign(prob_info, blocks, bays, deadline):
    """CYCLE 10 — z3-AWARE reassignment local search (the realize-gap lever).
    Start at the preferred assignment (z3≈0). Repeatedly relieve a tardy bay by
    moving ONE block to its cheapest-z3 alternative fitting bay (free z3=0 moves
    first), accepting only moves that LOWER total obj (first-improvement → strictly
    monotone, no cycling). Move evaluation re-packs ONLY the 2 affected bays (fast
    single-order bbox, cached by membership) and updates z2/z3 closed-form — so
    hundreds of moves fit the budget. The winning assignment is then packed with
    the full CELLS machinery + check_feasibility. Returns (obj, sol) | None.

    Rationale (INSIGHTS §4): the competitor reaches z1=0 at TINY z3 by a minimal
    precise spill; our `_assign_capped` spills crudely (z3 explodes). This searches
    the z3-cheap moves directly. obj-gated downstream ⇒ never regresses / never −1."""
    import os as _os
    n = len(blocks); nb = len(bays)
    if nb < 2:
        return None
    t_now = time.monotonic()
    search_dl = t_now + 0.6 * max(0.0, deadline - t_now)   # reserve 40% for final cells pack
    geo = {b: _orient_bboxes(b, blocks[b]) for b in range(n)}
    fits = {b: _fits_per_bay(b, blocks[b], bays) for b in range(n)}
    prefs = {b: blocks[b].get("bay_preferences", [0.0] * nb) for b in range(n)}
    smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
    wl = [float(blocks[b]["workload"]) for b in range(n)]
    areas = [max(1.0, bays[j].width * bays[j].height) for j in range(nb)]
    avg = sum(areas) / nb
    u = [avg / a for a in areas]

    cand_lim = int(_os.environ.get("OGC_REASSIGN_CANDS", "60"))
    gen_cap = int(_os.environ.get("OGC_REASSIGN_GENCAP", "4000"))
    w1 = prob_info.get("weights", {}).get("w1", 1.0)
    w2 = prob_info.get("weights", {}).get("w2", 1.0)
    w3 = prob_info.get("weights", {}).get("w3", 1.0)
    _pcache = {}
    _pcache_acc = {}
    # H11 (accurate-z1): Phase B's move-eval z1 via the DENSE cells packer instead of
    # the conservative bbox proxy (bbox-disjoint ⊂ cell-disjoint ⇒ bbox OVER-estimates
    # tardiness ⇒ rejects z3-reducing moves that actually keep z1=0). Gated OGC_ACCZ1
    # (default off; reversible). Cells is Shapely-heavy → only used in the bounded
    # Phase B, never the fast main loop.
    _accz1 = (_os.environ.get("OGC_ACCZ1", "0").strip().lower()
              not in ("0", "false", "no", "off"))

    def packbay(j, mem):
        key = (j, frozenset(mem))
        r = _pcache.get(key)
        if r is not None:
            return r
        if not mem:
            r = ({}, 0.0)
        else:
            order = sorted(mem, key=lambda b: (int(blocks[b]["due_date"]),
                                               int(blocks[b]["release_time"])))
            out, t = _pack_one_bbox(order, blocks, bays[j], geo, search_dl)
            r = (out, t) if out is not None else (None, math.inf)
        _pcache[key] = r
        return r

    def packbay_acc(j, mem):
        """Accurate (dense footprint-cell) tardiness for one bay — the H11 z1 oracle."""
        key = (j, frozenset(mem))
        r = _pcache_acc.get(key)
        if r is not None:
            return r
        if not mem:
            r = ({}, 0.0)
        else:
            out, t = _pack_one_cells(sorted(mem), blocks, bays[j], search_dl)
            r = (out, t) if out is not None else (None, math.inf)
        _pcache_acc[key] = r
        return r

    def z2_of(loads):
        vals = [u[j] * loads[j] for j in range(nb)]
        return math.floor(max(vals) - min(vals)) if nb >= 2 else 0.0

    def run_search(allow_swaps):
        """One local-search pass from the preferred assignment, optimising the FAST
        bbox-proxy obj. Returns the final per-bay member lists."""
        assign = {}
        members = [set() for _ in range(nb)]
        for b in range(n):
            f = fits[b]
            j = max(f, key=lambda k: prefs[b][k]) if f else 0
            assign[b] = j; members[j].add(b)
        tard = [packbay(j, members[j])[1] for j in range(nb)]
        loads = [sum(wl[b] for b in members[j]) for j in range(nb)]
        z1 = sum(tard); z3 = sum(smax[b] - prefs[b][assign[b]] for b in range(n))
        obj = w1 * z1 + w2 * z2_of(loads) + w3 * z3
        moves = 0
        while moves < 1000 and time.monotonic() < search_dl:
            if z1 <= 0:
                break
            tardy = [j for j in range(nb) if tard[j] > 0]
            cands = []     # (z3cost, kind, ...) — z3-cheap (often improving) first
            for j in tardy:                                   # one-way MOVES
                for b in members[j]:
                    for j2 in fits[b]:
                        if j2 != j:
                            cands.append((prefs[b][j] - prefs[b][j2], "M", b, j, j2))
            if allow_swaps:                                   # 2-opt SWAPS
                stop = False
                for j1 in tardy:
                    for b1 in members[j1]:
                        for j2 in fits[b1]:
                            if j2 == j1:
                                continue
                            for b2 in members[j2]:
                                if j1 not in fits[b2]:
                                    continue
                                dz3 = ((prefs[b1][j1] - prefs[b1][j2])
                                       + (prefs[b2][j2] - prefs[b2][j1]))
                                cands.append((dz3, "S", b1, b2, j1, j2))
                                if len(cands) > gen_cap:
                                    stop = True; break
                            if stop:
                                break
                        if stop:
                            break
                    if stop:
                        break
            cands.sort(key=lambda c: c[0])
            applied = False; seen = 0
            for c in cands:
                if seen >= cand_lim or time.monotonic() >= search_dl:
                    break
                seen += 1
                if c[1] == "M":
                    _z3c, _k, b, j, j2 = c
                    ts = packbay(j, members[j] - {b})[1]
                    td = packbay(j2, members[j2] | {b})[1]
                    if ts == math.inf or td == math.inf:
                        continue
                    nz1 = z1 - tard[j] - tard[j2] + ts + td
                    nl = loads[:]; nl[j] -= wl[b]; nl[j2] += wl[b]
                    nobj = w1 * nz1 + w2 * z2_of(nl) + w3 * (z3 + _z3c)
                    if nobj < obj - 1e-9:
                        members[j].discard(b); members[j2].add(b); assign[b] = j2
                        tard[j] = ts; tard[j2] = td; loads = nl
                        z1 = nz1; z3 += _z3c; obj = nobj
                        moves += 1; applied = True; break
                else:
                    dz3, _k, b1, b2, j1, j2 = c
                    ts = packbay(j1, (members[j1] - {b1}) | {b2})[1]
                    td = packbay(j2, (members[j2] - {b2}) | {b1})[1]
                    if ts == math.inf or td == math.inf:
                        continue
                    nz1 = z1 - tard[j1] - tard[j2] + ts + td
                    nl = loads[:]
                    nl[j1] += wl[b2] - wl[b1]; nl[j2] += wl[b1] - wl[b2]
                    nobj = w1 * nz1 + w2 * z2_of(nl) + w3 * (z3 + dz3)
                    if nobj < obj - 1e-9:
                        members[j1].discard(b1); members[j1].add(b2)
                        members[j2].discard(b2); members[j2].add(b1)
                        assign[b1] = j2; assign[b2] = j1
                        tard[j1] = ts; tard[j2] = td; loads = nl
                        z1 = nz1; z3 += dz3; obj = nobj
                        moves += 1; applied = True; break
            if not applied:
                break

        # PHASE B — z2/z3 polish at z1=0. EXPERIMENTAL, default OFF (OGC_PHASEB=1):
        # tested on prob_3/10 (the +4% near-misses) — found NO obj-lowering move that
        # keeps z1=0 (every z2-reducing move breaks z1=0 under the bbox proxy; the gap
        # is a genuine z1↔z2 Pareto point the competitor sits marginally better on).
        # Kept for future accurate-z1 search; off by default (adds cost, no payoff).
        _phaseb = (_os.environ.get("OGC_PHASEB", "0").strip().lower()
                   not in ("0", "false", "no", "off"))
        # H11: OGC_ACCZ1 implies Phase B, evaluated with the DENSE cells packer. Re-base
        # the per-bay tardiness on cells (bbox z1=0 ⇒ cells z1=0 since bbox-disjoint ⊂
        # cell-disjoint) so move deltas are cells-consistent.
        pb_eval = packbay
        if _accz1:
            _phaseb = True
            pb_eval = packbay_acc
            tard = [pb_eval(j, members[j])[1] for j in range(nb)]
            z1 = sum(tard); obj = w1 * z1 + w2 * z2_of(loads) + w3 * z3
        while _phaseb and z1 <= 1e-9 and moves < 2000 and time.monotonic() < search_dl:
            z2cur = z2_of(loads)
            cands = []
            for j in range(nb):
                for b in members[j]:
                    for j2 in fits[b]:
                        if j2 == j:
                            continue
                        nl = loads[:]; nl[j] -= wl[b]; nl[j2] += wl[b]
                        de = w2 * (z2_of(nl) - z2cur) + w3 * (prefs[b][j] - prefs[b][j2])
                        if de < -1e-9:
                            cands.append((de, "M", b, j, j2))
            stop = False
            for j1 in range(nb):
                for b1 in members[j1]:
                    for j2 in fits[b1]:
                        if j2 == j1:
                            continue
                        for b2 in members[j2]:
                            if j1 not in fits[b2]:
                                continue
                            nl = loads[:]
                            nl[j1] += wl[b2] - wl[b1]; nl[j2] += wl[b1] - wl[b2]
                            ddz3 = ((prefs[b1][j1] - prefs[b1][j2])
                                    + (prefs[b2][j2] - prefs[b2][j1]))
                            de = w2 * (z2_of(nl) - z2cur) + w3 * ddz3
                            if de < -1e-9:
                                cands.append((de, "S", b1, b2, j1, j2))
                                if len(cands) > gen_cap:
                                    stop = True; break
                        if stop:
                            break
                    if stop:
                        break
                if stop:
                    break
            if not cands:
                break
            cands.sort(key=lambda c: c[0])
            applied = False; seen = 0
            for c in cands:
                if seen >= cand_lim or time.monotonic() >= search_dl:
                    break
                seen += 1
                if c[1] == "M":
                    _de, _k, b, j, j2 = c
                    ts = pb_eval(j, members[j] - {b})[1]
                    td = pb_eval(j2, members[j2] | {b})[1]
                    if ts == math.inf or td == math.inf:
                        continue
                    nz1 = z1 - tard[j] - tard[j2] + ts + td
                    if nz1 > 1e-9:
                        continue                              # must keep z1=0
                    nl = loads[:]; nl[j] -= wl[b]; nl[j2] += wl[b]
                    dz3 = prefs[b][j] - prefs[b][j2]
                    nobj = w1 * nz1 + w2 * z2_of(nl) + w3 * (z3 + dz3)
                    if nobj < obj - 1e-9:
                        members[j].discard(b); members[j2].add(b); assign[b] = j2
                        tard[j] = ts; tard[j2] = td; loads = nl
                        z1 = nz1; z3 += dz3; obj = nobj
                        moves += 1; applied = True; break
                else:
                    _de, _k, b1, b2, j1, j2 = c
                    ts = pb_eval(j1, (members[j1] - {b1}) | {b2})[1]
                    td = pb_eval(j2, (members[j2] - {b2}) | {b1})[1]
                    if ts == math.inf or td == math.inf:
                        continue
                    nz1 = z1 - tard[j1] - tard[j2] + ts + td
                    if nz1 > 1e-9:
                        continue
                    nl = loads[:]
                    nl[j1] += wl[b2] - wl[b1]; nl[j2] += wl[b1] - wl[b2]
                    ddz3 = ((prefs[b1][j1] - prefs[b1][j2])
                            + (prefs[b2][j2] - prefs[b2][j1]))
                    nobj = w1 * nz1 + w2 * z2_of(nl) + w3 * (z3 + ddz3)
                    if nobj < obj - 1e-9:
                        members[j1].discard(b1); members[j1].add(b2)
                        members[j2].discard(b2); members[j2].add(b1)
                        assign[b1] = j2; assign[b2] = j1
                        tard[j1] = ts; tard[j2] = td; loads = nl
                        z1 = nz1; z3 += ddz3; obj = nobj
                        moves += 1; applied = True; break
            if not applied:
                break
        return [list(m) for m in members]

    # TWO passes: moves-only (reliable) then moves+swaps (z3-cheaper). The bbox
    # search-proxy can mislead the more-aggressive swap pass, so final-pack EACH
    # pass with cells+cpsat and keep the best TRUE obj ⇒ swaps never regress
    # moves-only, but capture their wins (e.g. prob_3 z3 446→88).
    best = None
    for allow_swaps in (False, True):
        if time.monotonic() >= deadline - 1.0:
            break
        mem_lists = run_search(allow_swaps)
        for fmode in ("cells", "cpsat"):
            if time.monotonic() >= deadline - 1.0:
                break
            r = _pack_members(mem_lists, bays, blocks, n, prob_info, deadline, fmode)
            if r is not None and (best is None or r[0] < best[0]):
                best = r
    return best


def _solve_feasspill(prob_info, blocks, bays, deadline):
    """CYCLE 18 — TARGETED-SPILL realize search (the realize-gap cracker). Start at
    preferred (z3≈0); spill the cheapest-z3 block from the most-tardy bay (cells-z1
    guide, with tabu) ONE AT A TIME; after each spill, pack the FULL assignment with
    box-decomp+cumulative (4 workers, solo in the main process) and keep the best TRUE
    obj. Finds the competitor regime (z1≈0 at LOW z3) that capped over-spills past
    (z3 cliff to ~9000) and the bbox-proxy reassign under-spills before (stuck z3~24):
    prob_13 preferred 3.47M → k=8 (z3=152) obj 192K (z1=8), an 8.8× cut. Early-stops a
    few steps past the sweet spot. obj-gated + fallback ⇒ never regresses / never −1.
    Returns (obj, sol) | None."""
    import os as _os
    n = len(blocks); nb = len(bays)
    if nb < 2:
        return None
    prefs = {b: blocks[b].get("bay_preferences", [0.0] * nb) for b in range(n)}
    smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
    fits = {b: _fits_per_bay(b, blocks[b], bays) for b in range(n)}
    geo = {b: _orient_bboxes(b, blocks[b]) for b in range(n)}
    _, m0 = _assign_preferred(blocks, bays)
    members = [set(m) for m in m0]
    # solo in main process AFTER the pool ⇒ box-decomp may use all cores.
    _os.environ["OGC_BD_WORKERS"] = _os.environ.get("OGC_FEASSPILL_WORKERS", "4")

    def bbox_tard(mem, j):                 # FAST guide (≈0.1s); cheap incremental update
        if not mem:
            return 0.0
        order = sorted(mem, key=lambda b: (int(blocks[b]["due_date"]),
                                           int(blocks[b]["release_time"])))
        out, t = _pack_one_bbox(order, blocks, bays[j], geo, time.monotonic() + 2.0)
        return t if out is not None else math.inf

    # PHASE A (cheap): build the spill TRAJECTORY with the fast bbox guide — spill the
    # cheapest-z3 block from the most-tardy bay one at a time, snapshotting each
    # assignment. Only the 2 changed bays are re-evaluated per step ⇒ ~O(steps) bbox
    # packs total (seconds), NOT cells-every-bay-every-step (the time-discipline bug).
    max_steps = int(_os.environ.get("OGC_FEASSPILL_STEPS", "24"))
    tard = [bbox_tard(members[j], j) for j in range(nb)]
    snaps = [[set(m) for m in members]]
    tabu = []
    for _step in range(1, max_steps + 1):
        if sum(tard) <= 0 or time.monotonic() >= deadline - 1.0:
            break
        j = max(range(nb), key=lambda k: tard[k])
        movable = ([b for b in members[j] if b not in tabu and any(k != j for k in fits[b])]
                   or [b for b in members[j] if any(k != j for k in fits[b])])
        if not movable:
            break
        b = min(movable, key=lambda b: (smax[b]
                - max(prefs[b][k] for k in fits[b] if k != j)))
        j2 = max((k for k in fits[b] if k != j), key=lambda k: prefs[b][k])
        members[j].discard(b); members[j2].add(b)
        tard[j] = bbox_tard(members[j], j); tard[j2] = bbox_tard(members[j2], j2)
        tabu.append(b)
        if len(tabu) > nb * 2:
            tabu = tabu[nb:]
        snaps.append([set(m) for m in members])

    # PHASE B (expensive, budget-strict): measure box-decomp+cumulative on snapshots
    # (every `every`-th), keep the best TRUE obj, early-stop after `patience` non-
    # improving measures. STRICT margin: never start a measure unless `margin` seconds
    # remain, and cap each box-decomp deadline at `deadline-1` ⇒ no wall overrun (−1).
    best = None; no_improve = 0
    every = int(_os.environ.get("OGC_FEASSPILL_EVERY", "2"))
    patience = int(_os.environ.get("OGC_FEASSPILL_PATIENCE", "4"))
    margin = float(_os.environ.get("OGC_FEASSPILL_MARGIN", "30"))
    idxs = list(range(0, len(snaps), every))
    for ii, k in enumerate(idxs):
        remaining = deadline - time.monotonic()
        if remaining < margin:
            break
        meas = max(8.0, (remaining - margin * 0.5) / max(1, len(idxs) - ii))
        hard = min(time.monotonic() + meas, deadline - 1.0)
        mem_lists = [list(m) for m in snaps[k]]
        r = _pack_members(mem_lists, bays, blocks, n, prob_info, hard, "boxdecomp")
        if r is not None and (best is None or r[0] < best[0] - 1e-9):
            best = r; no_improve = 0
        elif best is not None:
            no_improve += 1
        if no_improve >= patience:
            break
    return best


def _pack_members(members, bays, blocks, n, prob_info, deadline, mode):
    """Pack a fixed bay-assignment (members per bay) and return (objective,
    solution) if feasible, else None. Positions/timing come from the packer."""
    placements = {}
    pt = _pack_all(members, placements, bays, blocks, deadline, mode=mode)
    if pt is None or len(pt) != n:
        return None
    sol = _build(placements, pt, n)
    chk = check_feasibility(prob_info, sol)
    if not chk.get("feasible"):
        return None
    return chk["objective"], sol


def _serialise(members, blocks):
    """Pure per-bay EDD serialisation timing (one block present at a time)."""
    timed = {}
    for mem in members:
        free = 0
        for b in sorted(mem, key=lambda b: (int(blocks[b]["due_date"]),
                                            int(blocks[b]["release_time"]))):
            R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
            entry = max(R, free); timed[b] = (entry, entry + P); free = entry + P
    return timed


def _build(placements, timed, n):
    ops = {}
    for b in range(n):
        j, oi, x, y = placements[b]
        entry, exit_ = timed[b]
        ops.setdefault(exit_, []).append({"type": "EXIT", "block_id": b, "bay_id": int(j)})
        ops.setdefault(entry, []).append({"type": "ENTRY", "block_id": b, "bay_id": int(j),
                                          "x": int(x), "y": int(y), "orient_idx": int(oi)})
    operations = {}
    for t in sorted(ops):
        operations[str(int(t))] = [o for o in ops[t] if o["type"] == "EXIT"] + \
                                  [o for o in ops[t] if o["type"] == "ENTRY"]
    return {"operations": operations}


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Parallel candidate evaluation (4 cores). Each candidate = (assignment, cells).
# A process pool evaluates them concurrently; main keeps the best feasible. The
# wall deadline is a monotonic timestamp (QPC / CLOCK_MONOTONIC are system-wide →
# comparable across processes), so workers self-bound. Falls back to sequential
# on any pool error (never breaks correctness).
# ---------------------------------------------------------------------------

_W_PROB = None


def _winit(prob_info):
    global _W_PROB
    _W_PROB = prob_info


def _solve_spec(args):
    """Top-level worker: solve ONE candidate (name, alpha, mode) against the
    pool's prob_info. mode ∈ {"bbox","cells","cpsat"}. Returns
    (objective, solution) | None."""
    name, alpha, mode, deadline_ts = args
    try:
        prob = _W_PROB
        blocks = prob["blocks"]; n = len(blocks)
        bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
        _FP_CACHE.clear(); _LAYER_CACHE.clear()
        if mode == "reassign":
            return _solve_reassign(prob, blocks, bays, deadline_ts)
        if name == "preferred":
            _, members = _assign_preferred(blocks, bays)
        elif name == "capped":
            _, members = _assign_capped(blocks, bays, alpha)
        else:
            _, members = _assign_balanced(blocks, bays)
        return _pack_members(members, bays, blocks, n, prob, deadline_ts, mode)
    except Exception:
        return None


def _spec_list():
    """Candidate spectrum. Greedy {assignment × {bbox, cells}} always; CP-SAT
    packing-by-scheduling specs (the residual-z1→0 lever) appended unless
    OGC_CPSAT is off. CP-SAT on PREFERRED (z3≈0) is the set1-win lever: realise
    the preferred assignment at z1=0 ⇒ obj≈z2 ⇒ win. capped(1.0) gives a slightly
    spread variant for bays the preferred assignment over-packs."""
    import os as _os
    specs = [("preferred", None, "bbox"), ("capped", 1.0, "bbox"),
             ("balanced", None, "bbox"), ("preferred", None, "cells"),
             ("capped", 1.0, "cells")]
    # CP-SAT packing-by-scheduling slot. Cycle 13 box-DECOMPOSITION (≤K-rect cover of
    # footprint cells, tighter than single-bbox cpsat) REPLACES single-bbox cpsat when
    # OGC_BOXDECOMP is on — it dominates cpsat per-bay (prob_11 z1 50 vs 61) and a
    # REPLACE (not add) keeps the pool size constant ⇒ no extra CPU contention ⇒ the
    # set2-starvation regression vector stays closed. Gate b9mm3qizl: BD on −21% obj on
    # the 5 hard set1 targets (z1-driven), 0 regression. Default OFF (live = c12, never
    # −1). See INSIGHTS 2026-06-15 cycle 13/15.
    if _os.environ.get("OGC_CPSAT", "1").strip().lower() not in ("0", "false", "no", "off"):
        _cp = ("boxdecomp" if _os.environ.get("OGC_BOXDECOMP", "0").strip().lower()
               not in ("0", "false", "no", "off") else "cpsat")
        specs += [("preferred", None, _cp), ("capped", 1.0, _cp)]
        # OGC_BOX_ALPHAS (default none): extra capped-assignment alphas for a
        # MINIMAL-SPILL search. The base specs only try preferred(α=∞) and
        # capped(α=1.0); the z3-over-spill losses (box drives z1→0 by over-spilling,
        # z3 ≫ competitor) need the z1↔z3 sweet spot BETWEEN them. A higher α spills
        # less (closer to preferred); obj-gated best-of keeps it only if it lowers obj.
        _ea = (_os.environ.get("OGC_BOX_ALPHAS", "") or "").strip()
        if _ea:
            for _a in _ea.split(","):
                try:
                    _av = float(_a)
                    if _av > 0:
                        specs += [("capped", _av, "cells"), ("capped", _av, _cp)]
                except Exception:
                    pass
    # Cycle 9 (crane-overlap): FALSIFIED as a z1 lever — produced layouts identical
    # to cells (base-disjoint is the binding constraint; overhang only frees upper
    # layers, which aren't binding) at 2-4× the cost. Default OFF; kept opt-in.
    if _os.environ.get("OGC_CRANE", "0").strip().lower() not in ("0", "false", "no", "off"):
        specs += [("preferred", None, "crane"), ("capped", 1.0, "crane")]
    # NOTE: cycle-10 reassignment is NOT a pool spec — it runs as PHASE 2 in the
    # main process AFTER the base pool (see algorithm()), so it can never starve the
    # base specs of CPU (which caused set2 regressions when it shared the pool).
    return specs


def algorithm(prob_info: dict, timelimit: float = 60.0) -> dict:
    t0 = time.monotonic()
    import os as _os0
    _reassign_on = (_os0.environ.get("OGC_REASSIGN", "1").strip().lower()
                    not in ("0", "false", "no", "off"))
    _feasspill_on = (_os0.environ.get("OGC_FEASSPILL", "0").strip().lower()
                     not in ("0", "false", "no", "off"))
    tl = max(1.0, float(timelimit))
    # Budget split: base pool gets the first `base_frac`, then SOLO main-process phases.
    # Cycle-18 feasspill (targeted-spill realize search) is the breakthrough z1-lever
    # ⇒ when on it gets the lion's share (base pool just seeds the incumbent/fallback)
    # and REPLACES reassign (same z3-aware purpose, far stronger). Else reassign (P2)
    # gets the slack. Base pool still finishes the fast greedy + bounded box-decomp.
    if _feasspill_on:
        base_frac = 0.30
    elif _reassign_on:
        base_frac = 0.65
    else:
        base_frac = 0.85
    deadline = t0 + tl * base_frac
    re_deadline = t0 + tl * 0.93
    _FP_CACHE.clear(); _LAYER_CACHE.clear()   # per-instance: block_id keys collide across instances
    _winit(prob_info)          # set _W_PROB for the sequential-fallback path
    blocks = prob_info["blocks"]
    n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob_info["bays"])]

    # Guaranteed-feasible serialised fallback (always in hand → never −1).
    p0, m0 = _assign_preferred(blocks, bays)
    fallback = _build(p0, _serialise(m0, blocks), n)
    best_sol = fallback
    cf = check_feasibility(prob_info, fallback)
    best_obj = cf["objective"] if cf.get("feasible") else math.inf

    # Evaluate the candidate spectrum (assignment × {bbox, cells, cpsat}) ACROSS
    # 4 CORES. Each spec is an independent full solve; the obj gate keeps the best
    # feasible (weight-adaptive: w1≫w3 favours spreading / CP-SAT to kill z1; large
    # w3 favours preferred). The pool uses map_async with a HARD timeout just under
    # the wall: a slow CP-SAT spec can never push past the time limit (→ −1) — on
    # timeout we keep whatever the fast specs returned plus the serialised
    # fallback. Sequential fallback only if the pool fails to START.
    import os as _os
    specs = _spec_list()
    results = []
    ran = False
    _par = (_os.environ.get("OGC_PARALLEL", "1").strip().lower()
            not in ("0", "false", "no", "off"))
    if _par and n >= 1:
        import multiprocessing as _mp
        try:
            ctx = _mp.get_context("spawn")
            pool = ctx.Pool(min(4, len(specs)), initializer=_winit,
                            initargs=(prob_info,))
            try:
                ar = pool.map_async(
                    _solve_spec, [(nm, a, md, deadline) for nm, a, md in specs])
                # Pool bounded just past the base deadline (specs self-stop at
                # `deadline`); phase-2 reassign uses the remaining slack.
                timeout = max(2.0, tl * (base_frac + 0.03) - (time.monotonic() - t0))
                results = ar.get(timeout=timeout)
                ran = True
            except _mp.TimeoutError:
                ran = True                     # we DID run; near the wall → keep fallback
                results = []
            finally:
                pool.terminate(); pool.join()
        except Exception:
            ran = False                        # pool failed to start → seq fallback OK
    if not ran:                                # sequential fallback (pool unavailable)
        results = []
        for nm, a, md in specs:
            if time.monotonic() >= deadline:
                break
            results.append(_solve_spec((nm, a, md, deadline)))
    for r in results:
        if r is not None and r[0] < best_obj - 1e-9:
            best_sol, best_obj = r[1], r[0]

    # PHASE 2 (cycle 10): z3-aware reassignment local search, run SOLO in the main
    # process with the leftover budget — no pool-core contention ⇒ base specs are
    # never starved (the set2-regression cause). obj-gated ⇒ never regresses, and
    # the re_deadline keeps it well inside the wall ⇒ never −1. Scales with TL:
    # tiny slack locally, large on the eval server (TL up to ~30 min).
    if _reassign_on and not _feasspill_on and time.monotonic() < re_deadline - 1.0:
        try:
            _FP_CACHE.clear(); _LAYER_CACHE.clear()
            r = _solve_reassign(prob_info, blocks, bays, re_deadline)
            if r is not None and r[0] < best_obj - 1e-9:
                best_sol, best_obj = r[1], r[0]
        except Exception:
            pass

    # PHASE 3 (cycle 18): TARGETED-SPILL realize search — the realize-gap cracker.
    # Solo in the main process (all cores for box-decomp), big budget slice. obj-gated
    # against the incumbent + the always-feasible fallback ⇒ never regresses / never −1.
    # 0.93 wall margin + the phase's internal `margin` ⇒ box-decomp build can't overrun.
    fs_deadline = t0 + tl * 0.93
    if _feasspill_on and time.monotonic() < fs_deadline - 2.0:
        try:
            _FP_CACHE.clear(); _LAYER_CACHE.clear()
            r = _solve_feasspill(prob_info, blocks, bays, fs_deadline)
            if r is not None and r[0] < best_obj - 1e-9:
                best_sol, best_obj = r[1], r[0]
        except Exception:
            pass
    return best_sol


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "instances/train/prob_1.json"
    prob = json.load(open(path, encoding="utf-8"))
    t = time.monotonic()
    sol = algorithm(prob, 60)
    dt = time.monotonic() - t
    chk = check_feasibility(prob, sol)
    print(f"{path}: feasible={chk.get('feasible')} obj={chk.get('objective')} "
          f"z1={chk.get('obj1')} z2={chk.get('obj2')} z3={chk.get('obj3')} wall={dt:.2f}s")
