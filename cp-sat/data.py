"""
data.py -- parse prob_info into typed specs shared by every CP-SAT model.

Nothing here makes a decision; it only reads the instance and precomputes
weight-adaptive constants (the weights span orders of magnitude across
instances, w1 in [667, 29630], so every model must be weight-aware).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import geom


@dataclass
class BlockSpec:
    bid: int
    R: int                 # release_time   (entry >= R)
    P: int                 # processing_time(exit - entry >= P; we use exit = entry + P)
    D: int                 # due_date       (tardiness = max(0, exit - D))
    workload: int          # for the z2 imbalance objective
    prefs: list[int]       # bay_preferences (one score per bay)
    max_pref: int          # max(prefs)  -> z3 deviation = max_pref - prefs[chosen bay]
    min_area: float        # smallest-orientation bbox area (master area relaxation demand)
    data: dict             # raw block dict (shape etc.) for Block construction
    fitting_bays: list[int] = field(default_factory=list)


@dataclass
class BaySpec:
    j: int
    W: int
    H: int
    u: float               # bay weight u_j = avg_bay_area / (W_j * H_j)
    bay: geom.Bay


@dataclass
class Problem:
    bays: list[BaySpec]
    blocks: list[BlockSpec]
    w1: float
    w2: float
    w3: float
    n_bays: int
    n_blocks: int


def parse(prob_info: dict) -> Problem:
    bays_data = prob_info["bays"]
    blocks_data = prob_info["blocks"]
    w = prob_info.get("weights", {}) or {}
    w1 = float(w.get("w1", 1.0))
    w2 = float(w.get("w2", 1.0))
    w3 = float(w.get("w3", 1.0))

    n_bays = len(bays_data)
    areas = [int(b["width"]) * int(b["height"]) for b in bays_data]
    avg_area = (sum(areas) / n_bays) if n_bays else 1.0

    bays: list[BaySpec] = []
    for j, bd in enumerate(bays_data):
        W, H = int(bd["width"]), int(bd["height"])
        u = avg_area / (W * H) if (W * H) else 1.0
        bays.append(BaySpec(j=j, W=W, H=H, u=u, bay=geom.Bay.from_dict(bd, j)))

    blocks: list[BlockSpec] = []
    for i, bd in enumerate(blocks_data):
        prefs = list(bd.get("bay_preferences", [0] * n_bays))
        fitting = [j for j in range(n_bays)
                   if geom.block_fits_bay(bd, bays[j].W, bays[j].H)]
        blocks.append(BlockSpec(
            bid=i,
            R=int(bd["release_time"]),
            P=int(bd["processing_time"]),
            D=int(bd["due_date"]),
            workload=int(bd.get("workload", 0)),
            prefs=prefs,
            max_pref=max(prefs) if prefs else 0,
            min_area=geom.min_footprint_area(bd),
            data=bd,
            fitting_bays=fitting or list(range(n_bays)),
        ))

    return Problem(bays=bays, blocks=blocks, w1=w1, w2=w2, w3=w3,
                   n_bays=n_bays, n_blocks=len(blocks))


def horizon(prob: Problem) -> int:
    """A safe upper bound on any entry/exit time: latest release/due plus the
    total processing time (worst case all blocks serialised in one bay)."""
    maxR = max((b.R for b in prob.blocks), default=0)
    maxD = max((b.D for b in prob.blocks), default=0)
    sumP = sum(b.P for b in prob.blocks)
    return int(max(maxR, maxD) + sumP + 1)
