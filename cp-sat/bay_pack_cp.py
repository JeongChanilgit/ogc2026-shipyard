"""
bay_pack_cp.py -- the per-bay CP-SAT packer (the LBBD subproblem / oracle).

Decides, for the blocks the master put in ONE bay, every per-block geometric +
temporal variable via CP-SAT:

    orientation o, position (x, y)   -- via the chosen candidate placement
    entry time                       -- IntVar  (exit = entry + P)

minimising the bay's tardiness under the EXACT shipyard rules (same-layer
collision + crane lowering/lifting j>=k + half-open / co-exit time semantics).

The crane rule stays exact while (x, y, o) are free because each block picks one
of a finite candidate pool and, for every interacting candidate pair, the five
checker booleans are precomputed once and gated on which candidates are chosen.

SCALABILITY.  A single CP-SAT model over a whole crowded bay (50+ blocks)
explodes -- both the O(n^2 c^2) boolean precompute and the packing search.  So:

    * small bay (<= MONO)  -> one CP-SAT solve over all blocks (often optimal).
    * large bay            -> incremental CP-SAT in EDD batches: each batch is a
                              small CP-SAT solve placing ~BATCH free blocks
                              against the already-placed blocks held as FIXED
                              obstacles (constants).  Every placement is still a
                              CP-SAT decision; only the batch order is heuristic.

Returns (placements, total_tardiness, status) with status in {"ok","nofit",
"timeout"}.  "nofit" (a block fits no candidate in this bay) is the genuine
infeasibility that the master turns into a no-good cut.
"""

from __future__ import annotations

import time

from ortools.sat.python import cp_model

import geom
from data import BaySpec, BlockSpec

MONO = 14          # bays with <= MONO blocks: single monolithic solve
BATCH = 8          # free blocks per incremental CP-SAT solve


def _cap_for(n_free: int, base_cap: int) -> tuple[int, int, int]:
    """Candidate-pool size (cap, nx, ny) for a solve with n_free free blocks.

    Kept small: candidate count drives BOTH the boolean-precompute cost
    (O(pairs * cand^2)) and the search size, so it is the main scalability knob.
    """
    if n_free <= 8:
        return min(base_cap, 14), 5, 3
    if n_free <= 14:
        return min(base_cap, 10), 4, 3
    return min(base_cap, 7), 3, 2


# -----------------------------------------------------------------------------
# Core: place `free` blocks against `fixed` obstacles, all geometry CP-SAT
# -----------------------------------------------------------------------------
def _solve_subset(
    baysp: BaySpec,
    free: list[BlockSpec],
    fixed: dict[int, dict],          # bid -> placement (x,y,orient_idx,entry,exit)
    horizon: int,
    time_budget: float,
    base_cap: int,
    warm: dict | None,
    workers: int,
    seed: int,
):
    """Returns (placements_for_free, status). status in {"ok","nofit","timeout"}."""
    if not free:
        return {}, "ok"
    W, H = baysp.W, baysp.H
    cap, nx, ny = _cap_for(len(free), base_cap)

    # fixed obstacles: layer polys + bbox each (constants), computed first so
    # their bbox edges can seed bottom-left abutment anchors for new candidates.
    flay: dict[int, list] = {}
    fbb: dict[int, tuple] = {}
    for fid, p in fixed.items():
        c = (p["orient_idx"], p["x"], p["y"])
        flay[fid] = geom.cand_layers(_DATA[fid], c)
        fbb[fid] = geom.cand_world_bbox(_DATA[fid], c)

    cand: dict[int, list[tuple[int, int, int]]] = {}
    clay: dict[int, list] = {}        # precomputed layer polys per candidate
    cbb: dict[int, list[tuple]] = {}  # world bbox per candidate
    warm_idx: dict[int, int] = {}
    for bs in free:
        cs = geom.gen_candidates(bs.data, W, H, cap=cap, nx=nx, ny=ny)
        if warm and bs.bid in warm:
            wo, wx, wy, _we = warm[bs.bid]
            wc = (int(wo), int(wx), int(wy))
            if wc in cs:
                cs.remove(wc)
            cs.insert(0, wc)
            warm_idx[bs.bid] = 0
        if not cs:
            return None, "nofit"
        cand[bs.bid] = cs
        clay[bs.bid] = [geom.cand_layers(bs.data, c) for c in cs]
        cbb[bs.bid] = [geom.cand_world_bbox(bs.data, c) for c in cs]

    m = cp_model.CpModel()
    sel, entry, expP, tard = {}, {}, {}, []
    for bs in free:
        b = bs.bid
        yv = [m.NewBoolVar(f"s_{b}_{c}") for c in range(len(cand[b]))]
        m.AddExactlyOne(yv)
        sel[b] = yv
        e = m.NewIntVar(bs.R, horizon, f"e_{b}")
        entry[b] = e
        expP[b] = bs.P
        t = m.NewIntVar(0, horizon, f"t_{b}")
        m.Add(t >= e + bs.P - bs.D)
        tard.append(t)

    ids = [bs.bid for bs in free]

    # --- free vs free --------------------------------------------------------
    for ia in range(len(ids)):
        a = ids[ia]
        ae = entry[a]
        ax = ae + expP[a]
        for ib in range(ia + 1, len(ids)):
            b = ids[ib]
            be = entry[b]
            bx = be + expP[b]
            for i, bba in enumerate(cbb[a]):
                sel_ai = sel[a][i]
                lay_ai = clay[a][i]
                for k, bbb in enumerate(cbb[b]):
                    if not geom.bbox_overlap(bba, bbb):
                        continue
                    coll, a_blk_b, b_blk_a = geom.booleans_from_layers(lay_ai, clay[b][k])
                    if not (coll or a_blk_b or b_blk_a):
                        continue
                    gate = [sel_ai, sel[b][k]]
                    if coll:
                        _disj(m, gate, [(ax, "<=", be), (bx, "<=", ae)])
                        continue
                    if a_blk_b:   # a obstructs b's entry AND exit
                        _disj(m, gate, [(be, "<=", ae - 1), (be, ">=", ax)])   # entry
                        _disj(m, gate, [(bx, "<=", ae), (bx, ">=", ax + 1)])   # exit
                    if b_blk_a:   # b obstructs a's entry AND exit
                        _disj(m, gate, [(ae, "<=", be - 1), (ae, ">=", bx)])
                        _disj(m, gate, [(ax, "<=", be), (ax, ">=", bx + 1)])

    # --- free vs fixed (one operand is constant) -----------------------------
    for bs in free:
        a = bs.bid
        ae = entry[a]
        ax = ae + expP[a]
        for fid, p in fixed.items():
            Ef, Xf = int(p["entry_time"]), int(p["exit_time"])
            for i, bba in enumerate(cbb[a]):
                if not geom.bbox_overlap(bba, fbb[fid]):
                    continue
                coll, a_blk_f, f_blk_a = geom.booleans_from_layers(clay[a][i], flay[fid])
                if not (coll or a_blk_f or f_blk_a):
                    continue
                gate = [sel[a][i]]
                if coll:
                    _disj(m, gate, [(ax, "<=", Ef), (Xf, "<=", ae)])
                    continue
                if a_blk_f:   # free obstructs fixed's entry AND exit
                    _disj(m, gate, [(Ef, "<=", ae - 1), (Ef, ">=", ax)])
                    _disj(m, gate, [(Xf, "<=", ae), (Xf, ">=", ax + 1)])
                if f_blk_a:   # fixed obstructs free's entry AND exit
                    _disj(m, gate, [(ae, "<=", Ef - 1), (ae, ">=", Xf)])
                    _disj(m, gate, [(ax, "<=", Ef), (ax, ">=", Xf + 1)])

    # Objective: minimise tardiness FIRST, then (as a strict tie-breaker that
    # never sacrifices tardiness) prefer bottom-left placements so each batch
    # leaves low-left room for the blocks placed later.
    Wr = W + 1
    comp_terms = []
    comp_max = 0
    for bs in free:
        b = bs.bid
        ranks = [c[2] * Wr + c[1] for c in cand[b]]   # y dominant, then x
        comp_max += max(ranks) if ranks else 0
        comp_terms.extend(sel[b][i] * ranks[i] for i in range(len(ranks)))
    K = comp_max + 1
    m.Minimize(K * sum(tard) + sum(comp_terms))

    if warm:
        for bs in free:
            if bs.bid in warm_idx:
                m.AddHint(sel[bs.bid][warm_idx[bs.bid]], 1)
            if bs.bid in warm:
                m.AddHint(entry[bs.bid], int(warm[bs.bid][3]))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, float(time_budget))
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, "timeout"

    out: dict[int, dict] = {}
    for bs in free:
        b = bs.bid
        ci = next(i for i, v in enumerate(sel[b]) if solver.Value(v) == 1)
        o, x, y = cand[b][ci]
        e = int(solver.Value(entry[b]))
        out[b] = {"x": int(x), "y": int(y), "orient_idx": int(o),
                  "entry_time": e, "exit_time": e + bs.P, "bay_id": baysp.j}
    return out, "ok"


# Module-level handle to raw block dicts so _solve_subset can build fixed Blocks.
_DATA: dict[int, dict] = {}


def solve_bay(
    baysp: BaySpec,
    block_specs: list[BlockSpec],
    horizon: int,
    time_budget: float,
    base_cap: int = 40,
    warm: dict | None = None,
    workers: int = 4,
    seed: int = 12345,
):
    """Public entry. Returns (placements, total_tardiness, status)."""
    if not block_specs:
        return {}, 0, "ok"
    for bs in block_specs:
        _DATA[bs.bid] = bs.data

    n = len(block_specs)
    if n <= MONO:
        place, status = _solve_subset(baysp, block_specs, {}, horizon,
                                      time_budget, base_cap, warm, workers, seed)
        if status != "ok":
            return None, None, status
        return place, _tardiness(place, block_specs), "ok"

    # incremental batches in EDD order
    t_end = time.monotonic() + max(0.5, time_budget)
    order = sorted(block_specs, key=lambda b: (b.D, b.R))
    placed: dict[int, dict] = {}
    i = 0
    while i < n:
        batch = order[i:i + BATCH]
        remain = t_end - time.monotonic()
        if remain < 0.5:
            return None, None, "timeout"
        n_left_batches = (n - i + BATCH - 1) // BATCH
        b_budget = max(0.5, remain / n_left_batches)
        bwarm = None
        if warm:
            bwarm = {b.bid: warm[b.bid] for b in batch if b.bid in warm}
        place, status = _solve_subset(baysp, batch, placed, horizon,
                                      b_budget, base_cap, bwarm, workers, seed)
        if status == "nofit":
            return None, None, "nofit"
        if status == "timeout" or place is None:
            return None, None, "timeout"
        placed.update(place)
        i += BATCH
    return placed, _tardiness(placed, block_specs), "ok"


def _tardiness(place: dict[int, dict], specs: list[BlockSpec]) -> int:
    by = {bs.bid: bs for bs in specs}
    return sum(max(0, p["exit_time"] - by[bid].D) for bid, p in place.items())


def _disj(m, gate, terms):
    """OR_i (lhs_i op_i rhs_i), enforced only when all `gate` literals hold."""
    lits = []
    for lhs, op, rhs in terms:
        lit = m.NewBoolVar("")
        if op == "<=":
            m.Add(lhs <= rhs).OnlyEnforceIf(lit)
        else:
            m.Add(lhs >= rhs).OnlyEnforceIf(lit)
        lits.append(lit)
    m.AddBoolOr(lits).OnlyEnforceIf(gate)
