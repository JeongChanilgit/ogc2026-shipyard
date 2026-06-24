"""Unit tests for the fixed-time decode primitives (src/fastfloor.py).

Spec-mandated shift check, RESULT (2026-06-12, prob_1): instance vertices are
FLOATS (e.g. -5.1498), so integer-shifted LOCAL raster cells are NOT exactly
equal to rasterising the float-translated world verts -- 8 layers differ
within the first 8 blocks (extra boundary cells on the shifted side).  Per
spec the shared shift cache was therefore demoted to a candidate-screening
heuristic, and every accepted/placed cell set comes from per-position DIRECT
rasterisation (_world_layer_cells).  These tests pin that decision.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

INSTANCE = ROOT / "instances" / "train" / "prob_1.json"


def _blocks():
    return json.loads(INSTANCE.read_text(encoding="utf-8"))["blocks"]


def test_world_cells_equal_direct_rasterise():
    """Load-bearing invariant: the cells the decoder stores for a placement
    are exactly the direct rasterisation of Block.layers_at_pos() -- the same
    conservative superset the baseline raster floor uses."""
    from utils import Block
    from baseline_greedy import _rasterize_layer_cells
    from fastfloor import _world_layer_cells

    blocks = _blocks()
    X, Y = 3, 5
    n_checked = 0
    for b in range(min(8, len(blocks))):
        blk = blocks[b]
        for oi in range(len(blk["shape"])):
            bl = Block(b, blk, X, Y, oi)
            got = _world_layer_cells(bl)
            want = [_rasterize_layer_cells(l) for l in bl.layers_at_pos()]
            assert got == want, (b, oi)
            n_checked += len(want)
    assert n_checked > 0


def test_shift_is_screening_only():
    """The spec decision procedure: compare integer-shifted local cells vs
    direct world rasterisation at (3, 5).  A mismatch is EXPECTED (float
    verts); whenever one exists the implementation must not treat the shift
    as exact -- pinned via the SCREENING ONLY contract marker."""
    from utils import Block
    from baseline_greedy import _rasterize_layer_cells
    from fastfloor import _local_layer_cells

    blocks = _blocks()
    X, Y = 3, 5
    mismatches = 0
    for b in range(min(8, len(blocks))):
        blk = blocks[b]
        for oi in range(len(blk["shape"])):
            local = _local_layer_cells(blk, oi)
            world = Block(b, blk, X, Y, oi).layers_at_pos()
            for loc, wverts in zip(local, world):
                shifted = frozenset((cx + X, cy + Y) for (cx, cy) in loc)
                if shifted != _rasterize_layer_cells(wverts):
                    mismatches += 1
    if mismatches:
        assert "SCREENING ONLY" in (_local_layer_cells.__doc__ or ""), (
            f"{mismatches} shifted!=direct layers but _local_layer_cells no "
            f"longer documents the screening-only contract -- if shift was "
            f"promoted back to load-bearing, this is unsound")


def test_time_disjoint_pairs_have_no_geometry_constraint():
    """eA <= aB (or eB <= aA) -> conditions 1-5 all false -> identical cells
    at the identical spot are allowed; open overlap forbids them."""
    from fastfloor import _ft_pair_ok

    cells = [frozenset({(0, 0), (1, 0)})]
    A = {"a": 0, "e": 10, "layers": cells, "n": 1}
    # B reuses the exact same spot after A exits (boundary co-time included).
    assert _ft_pair_ok(A, 10, 20, cells, 0, 0, 1) is True
    assert _ft_pair_ok(A, 12, 20, cells, 0, 0, 1) is True
    # B before A enters.
    B_before = {"a": 10, "e": 20, "layers": cells, "n": 1}
    assert _ft_pair_ok(B_before, 0, 10, cells, 0, 0, 1) is True
    # Open overlap -> collide forbidden.
    assert _ft_pair_ok(A, 5, 15, cells, 0, 0, 1) is False
    # Co-exit (eB == eA) counts as A blocking B's exit (condition 2).
    assert _ft_pair_ok(A, 0, 10, cells, 0, 0, 1) is False
    # Disjoint cells are fine even with full overlap.
    other = [frozenset({(5, 5)})]
    assert _ft_pair_ok(A, 5, 15, other, 0, 0, 1) is True
    # Shift is applied: other cells shifted onto A's cells -> forbidden.
    assert _ft_pair_ok(A, 5, 15, other, -4, -5, 1) is False
