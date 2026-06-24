"""
geom.py -- geometry layer for the all-CP-SAT solver.

This module is the ONLY place that touches polygon geometry.  It does two jobs:

  1. CANDIDATE ENUMERATION.  For each block it enumerates a finite pool of
     placements  (orientation, x, y).  This is NOT a heuristic "decision" --
     it is the explicit, finite domain of the (orient, x, y) decision
     variables that the per-bay CP-SAT model then *chooses* among.  By making
     the geometry static per candidate we can precompute exact crane booleans
     (see #2) and still let CP-SAT own the placement decision.

  2. EXACT PAIR BOOLEANS.  For any two *placed* candidates it returns the same
     five booleans the official checker uses (one same-layer collision + four
     directional crane-access booleans).  These feed the reified disjunctive
     time constraints in bay_pack_cp.py, reproducing the checker's j>=k crane
     rule and half-open time semantics exactly.

All geometry is delegated to the official, do-not-modify ``src/utils.py``
(Block / Bay / check_collisions / check_entry / check_exit) so that what the
CP-SAT model believes is feasible is bit-identical to what the grader checks.
"""

from __future__ import annotations

import math
import os
import sys

# --- bind to the official checker geometry (src/utils.py) --------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import utils  # noqa: E402  (official; do not modify)
from utils import Bay, Block, check_collisions, check_entry, check_exit  # noqa: E402

_EPS = 1e-9


# -----------------------------------------------------------------------------
# Per-orientation geometry
# -----------------------------------------------------------------------------
def orient_bbox(block_data: dict, o: int) -> tuple[float, float, float, float]:
    """Local-coordinate axis-aligned bbox (minx, miny, maxx, maxy) of orientation o.

    Covers the union of all layers.  The reference vertex (first vertex of the
    first layer) is the local origin (0, 0); minx/miny are therefore <= 0 and
    maxx/maxy >= 0 in general.
    """
    layers = utils._resolve_layers(block_data["shape"][o]["layers"])
    verts = [v for layer in layers for v in layer]
    if not verts:
        return (0.0, 0.0, 1.0, 1.0)
    return utils._bounding_box(verts)


def orient_geoms(block_data: dict) -> list[tuple]:
    """List over orientations: (o, minx, miny, maxx, maxy, w, h)."""
    out = []
    for o in range(len(block_data["shape"])):
        minx, miny, maxx, maxy = orient_bbox(block_data, o)
        out.append((o, minx, miny, maxx, maxy, maxx - minx, maxy - miny))
    return out


def block_fits_bay(block_data: dict, W: int, H: int) -> bool:
    """True iff at least one orientation admits an INTEGER placement in W x H.

    A continuous bbox fit (w <= W) is NOT sufficient: the grader requires
    integer (x, y), and a sub-unit slack window can contain no integer position
    (e.g. the reference point forces x into (2.3, 2.6) -> no integer). We must
    use the same integer range test as gen_candidates, or a block can be
    "assigned" to a bay it cannot actually be placed in.
    """
    for _o, minx, miny, maxx, maxy, w, h in orient_geoms(block_data):
        if w > W + _EPS or h > H + _EPS:
            continue
        xlo = math.ceil(-minx - _EPS)
        xhi = math.floor(W - maxx + _EPS)
        ylo = math.ceil(-miny - _EPS)
        yhi = math.floor(H - maxy + _EPS)
        if xhi >= xlo and yhi >= ylo:
            return True
    return False


def min_footprint_area(block_data: dict) -> float:
    """Smallest orientation bbox area -- an optimistic (lower-bound) space demand
    used as the per-bay area-cumulative demand in the master relaxation."""
    best = None
    for _o, _mnx, _mny, _mxx, _mxy, w, h in orient_geoms(block_data):
        a = max(0.0, w) * max(0.0, h)
        if best is None or a < best:
            best = a
    return best if best is not None else 1.0


# -----------------------------------------------------------------------------
# Candidate enumeration  (the finite domain of the (orient, x, y) variable)
# -----------------------------------------------------------------------------
def _axis_values(lo: int, hi: int, n: int, extra: list[int] | None = None) -> list[int]:
    """Integer anchor values in [lo, hi]: the two walls, an evenly spaced grid of
    size ~n, plus any ``extra`` reference anchors that fall in range."""
    if hi < lo:
        return []
    vals = {lo, hi}
    if n >= 1 and hi > lo:
        for k in range(n + 1):
            vals.add(lo + round(k * (hi - lo) / n))
    if extra:
        for v in extra:
            iv = int(round(v))
            if lo <= iv <= hi:
                vals.add(iv)
    return sorted(vals)


def gen_candidates(
    block_data: dict,
    W: int,
    H: int,
    cap: int = 40,
    nx: int = 7,
    ny: int = 3,
    x_extra: list[int] | None = None,
    y_extra: list[int] | None = None,
) -> list[tuple[int, int, int]]:
    """Enumerate fitting (orient, x, y) candidate placements for one block.

    (x, y) are reference-point coordinates in bay space (what Block expects).
    Result is capped with a bottom-left-biased, orientation-diverse subset.
    """
    per_orient: list[list[tuple[int, int, int]]] = []
    for o, minx, miny, maxx, maxy, w, h in orient_geoms(block_data):
        if w > W + _EPS or h > H + _EPS:
            continue
        # x ref range: x+minx >= 0  and  x+maxx <= W
        xlo = math.ceil(-minx - _EPS)
        xhi = math.floor(W - maxx + _EPS)
        ylo = math.ceil(-miny - _EPS)
        yhi = math.floor(H - maxy + _EPS)
        if xhi < xlo or yhi < ylo:
            continue
        xs = _axis_values(xlo, xhi, nx, x_extra)
        ys = _axis_values(ylo, yhi, ny, y_extra)
        oc = [(o, x, y) for y in ys for x in xs]
        # bottom-left bias within the orientation
        oc.sort(key=lambda c: (c[2], c[1]))
        per_orient.append(oc)

    if not per_orient:
        return []

    # Round-robin across orientations so the cap keeps orientation diversity.
    out: list[tuple[int, int, int]] = []
    idx = 0
    while len(out) < cap:
        progressed = False
        for oc in per_orient:
            if idx < len(oc):
                out.append(oc[idx])
                progressed = True
                if len(out) >= cap:
                    break
        if not progressed:
            break
        idx += 1
    return out


def make_block(block_id: int, block_data: dict, x: int, y: int, orient: int) -> Block:
    """Construct an official Block placed at (x, y) with the given orientation."""
    return Block(block_id=block_id, block_data=block_data, x=int(x), y=int(y),
                 orient_idx=int(orient))


def cand_world_bbox(block_data: dict, cand: tuple[int, int, int]) -> tuple[float, float, float, float]:
    """World-coordinate bbox of a candidate placement (for cheap AABB pre-filter)."""
    o, x, y = cand
    minx, miny, maxx, maxy = orient_bbox(block_data, o)
    return (x + minx, y + miny, x + maxx, y + maxy)


def bbox_overlap(a: tuple, b: tuple) -> bool:
    """Strict AABB overlap (touching edges do not overlap), matching utils."""
    return not (a[2] <= b[0] + _EPS or b[2] <= a[0] + _EPS
                or a[3] <= b[1] + _EPS or b[3] <= a[1] + _EPS)


# -----------------------------------------------------------------------------
# Fast layer-polygon precompute + booleans
# -----------------------------------------------------------------------------
# A placement's geometry is a list of (shapely_polygon_or_None, layer_bbox) over
# its layers, built ONCE per candidate.  Deriving the booleans from these reuses
# the polygons across every pair test instead of rebuilding them per checker
# call -- the single biggest construction-time win.

def cand_layers(block_data: dict, cand: tuple[int, int, int]) -> list[tuple]:
    """Per-layer (polygon, bbox) for a candidate placement, world coordinates.

    Uses utils._poly_from_verts (lru-cached, buffer(0) validity repair) so the
    geometry is bit-identical to what check_entry / check_exit / check_collisions
    construct internally.
    """
    o, x, y = cand
    blk = make_block(0, block_data, x, y, o)
    out = []
    for verts in blk.layers_at_pos():
        poly = utils._poly_from_verts(verts)
        bb = utils._bounding_box(verts) if verts else None
        out.append((poly, bb))
    return out


def _layer_hit(la: tuple, lb: tuple) -> bool:
    """True iff two layers' polygons overlap with positive area (matches utils:
    strict-AABB pre-filter via utils._bb_overlap, then intersection.area > 0)."""
    pa, ba = la
    pb, bb = lb
    if pa is None or pb is None or ba is None or bb is None:
        return False
    if not utils._bb_overlap(ba, bb):
        return False
    inter = pa.intersection(pb)
    return (not inter.is_empty) and inter.area > 0


def booleans_from_layers(LA: list[tuple], LB: list[tuple]) -> tuple[bool, bool, bool]:
    """Return (coll, A_blocks_B, B_blocks_A) from precomputed layer geometry.

    coll        : same layer index k overlaps (k < min(nA, nB)).
    A_blocks_B  : exists B-layer k and A-layer j >= k with A[j] ∩ B[k] > 0
                  (A obstructs the crane lowering/lifting B -- entry == exit).
    B_blocks_A  : symmetric.
    """
    nA, nB = len(LA), len(LB)
    coll = any(_layer_hit(LA[k], LB[k]) for k in range(min(nA, nB)))
    a_blk_b = False
    for k in range(nB):
        if any(_layer_hit(LA[j], LB[k]) for j in range(k, nA)):
            a_blk_b = True
            break
    b_blk_a = False
    for k in range(nA):
        if any(_layer_hit(LB[j], LA[k]) for j in range(k, nB)):
            b_blk_a = True
            break
    return coll, a_blk_b, b_blk_a


# -----------------------------------------------------------------------------
# Exact pair booleans via the official checker (slow reference path)
# -----------------------------------------------------------------------------
def pair_booleans(bay: Bay, blkA: Block, blkB: Block) -> tuple[bool, bool, bool, bool, bool]:
    """Return (coll, A_blk_B_entry, B_blk_A_entry, A_blk_B_exit, B_blk_A_exit).

    coll          : A and B overlap at a shared layer index (Stage-4 collision).
    A_blk_B_entry : with A already present, the crane cannot LOWER B (Stage-2).
    B_blk_A_entry : with B already present, the crane cannot LOWER A.
    A_blk_B_exit  : with A present, the crane cannot LIFT B out (Stage-3).
    B_blk_A_exit  : with B present, the crane cannot LIFT A out.

    These are time-INDEPENDENT functions of the two placements, exactly as the
    checker computes them; the time coupling is added by the CP-SAT model.
    """
    coll = bool(check_collisions(bay, [blkA, blkB]))
    a_blk_b_entry = bool(check_entry(bay, [blkA], blkB, fast=True))
    b_blk_a_entry = bool(check_entry(bay, [blkB], blkA, fast=True))
    a_blk_b_exit = bool(check_exit(bay, [blkA], blkB, fast=True))
    b_blk_a_exit = bool(check_exit(bay, [blkB], blkA, fast=True))
    return coll, a_blk_b_entry, b_blk_a_entry, a_blk_b_exit, b_blk_a_exit
