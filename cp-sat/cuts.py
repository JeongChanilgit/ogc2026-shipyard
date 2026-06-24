"""
cuts.py -- LBBD cut-set selection.

When the per-bay packer realises a tardiness higher than the master's
optimistic relaxation, the master over-packed that bay.  We hand it back a
cardinality cut over a set of blocks that are *mutually present at the same
instant* -- a time-overlap clique -- telling it "no more than k-1 of these can
share this bay".  The clique is the maximum number of intervals alive at any
single time point (max-overlap on an interval graph, found by a sweep).
"""

from __future__ import annotations


def time_overlap_clique(placements: dict[int, dict]) -> list[int]:
    """Return the largest set of block ids whose [entry, exit) intervals are all
    alive at one common instant.  Empty/singleton if nothing overlaps."""
    if len(placements) < 2:
        return list(placements.keys())
    events = []  # (time, +1 entry / -1 exit, bid)
    for bid, p in placements.items():
        events.append((p["entry_time"], 1, bid))
        events.append((p["exit_time"], -1, bid))
    # process exits before entries at the same instant (half-open intervals)
    events.sort(key=lambda e: (e[0], e[1]))
    active: set[int] = set()
    best: set[int] = set()
    for _t, kind, bid in events:
        if kind == 1:
            active.add(bid)
            if len(active) > len(best):
                best = set(active)
        else:
            active.discard(bid)
    return sorted(best)
