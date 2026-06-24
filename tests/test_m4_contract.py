"""M4 contract test: the decoder's force-place certificate plumbing.

The time-serialising per-bay decoder rarely needs the empty-window force-place
fallback (even dense, tight instances pack without it), so op_cut_destroy stays
dormant on realistic instances.  These tests therefore lock the M4 *contract*
directly -- independent of whether any instance force-places -- so the cache
shape change can never silently break an existing caller:

  * _decode_bay returns (result, forced_ids) with forced_ids a set.
  * _Decoder.decode()      keeps the (result, tardiness) 2-tuple FIREWALL.
  * _Decoder.decode_full() returns (result, tardiness, forced_ids:frozenset).
  * decode() and decode_full() are consistent (same cached result + tardiness).
  * a fabricated cut_store entry is a frozenset of (bay, frozenset(ids)) -- the
    shape op_cut_destroy / the op_shift consult rely on.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import myalgorithm as M  # noqa: E402
from utils import Bay  # noqa: E402


def _example():
    p = ROOT / "instances" / "example" / "example_B2_b10.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_decode_bay_returns_result_and_forced_set():
    prob = _example()
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    order = list(range(min(4, len(prob["blocks"]))))
    out = M._decode_bay(bays[0], 0, order, prob["blocks"])
    assert isinstance(out, tuple) and len(out) == 2
    res, forced = out
    assert res is None or isinstance(res, dict)
    assert isinstance(forced, set)  # the M4 certificate (possibly empty)


def test_decoder_firewall_and_full_are_consistent():
    prob = _example()
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    dec = M._Decoder(bays, prob["blocks"], alt_threshold=40)
    ids = list(range(min(5, len(prob["blocks"]))))

    res2 = dec.decode(0, ids)         # FIREWALL: legacy 2-tuple
    res3 = dec.decode_full(0, ids)    # full 3-tuple

    assert isinstance(res2, tuple) and len(res2) == 2
    assert isinstance(res3, tuple) and len(res3) == 3
    assert res2[0] == res3[0]                 # same per-bay result (cached)
    assert res2[1] == res3[1]                 # same tardiness
    assert isinstance(res3[2], frozenset)     # forced_ids certificate


def test_cut_store_entry_shape():
    # The shape op_cut_destroy records and the op_shift consult look up:
    # (bay_idx:int, frozenset(block_ids)).  Membership must be hashable/stable.
    store = set()
    store.add((0, frozenset({1, 2, 3})))
    assert (0, frozenset({3, 2, 1})) in store      # order-independent
    assert (1, frozenset({1, 2, 3})) not in store   # bay-specific
