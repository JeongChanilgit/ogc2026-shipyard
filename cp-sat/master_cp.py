"""
master_cp.py -- the CP-SAT LBBD master (assignment + relaxed schedule).

Owns the decisions that the per-bay packer cannot see across bays:

    * bay assignment x[b, j]        (each block to exactly one fitting bay)
    * a RELAXED entry schedule      (area-cumulative per bay, not exact packing)
    * z2 workload imbalance         (exact, from the assignment)
    * z3 preference penalty         (exact, from the assignment)

It minimises the FULL weighted objective  w1*Z1 + w2*Z2 + w3*Z3  on the same
1000x integer basis the grader uses, so the master's notion of "good" matches
the real score.  Z1 here is only a lower bound (the cumulative relaxation); the
per-bay packer computes the true Z1 and feeds discrepancies back as cuts.

Cuts learned by the LBBD loop:
    no-good (j, S)       : block set S cannot all live in bay j  -> Sum x[b,j] <= |S|-1
    cardinality (j,S,k)  : at most k of a time-conflicting set S fit in bay j
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from data import Problem

_S = 1000  # shared integer basis: every objective term is lifted to 1000x


def solve_master(
    prob: Problem,
    nogoods: list[tuple[int, frozenset]],
    card_cuts: list[tuple[int, frozenset, int]],
    horizon: int,
    time_budget: float,
    rho: float = 0.85,
    hint: dict | None = None,
    workers: int = 4,
    seed: int = 1234,
):
    """Returns (assign, relaxed_bay_z1) or (None, None).

    assign:          {bid: bay_j}
    relaxed_bay_z1:  {bay_j: int}  -- the master's (optimistic) per-bay tardiness.
    """
    m = cp_model.CpModel()
    n_bays = prob.n_bays

    x: dict[tuple[int, int], "cp_model.IntVar"] = {}
    entry: dict[int, "cp_model.IntVar"] = {}
    tard: dict[int, "cp_model.IntVar"] = {}

    for bs in prob.blocks:
        b = bs.bid
        fb = bs.fitting_bays
        row = []
        for j in fb:
            v = m.NewBoolVar(f"x_{b}_{j}")
            x[(b, j)] = v
            row.append(v)
        m.AddExactlyOne(row)
        e = m.NewIntVar(bs.R, horizon, f"e_{b}")
        t = m.NewIntVar(0, horizon, f"t_{b}")
        m.Add(t >= e + bs.P - bs.D)
        entry[b] = e
        tard[b] = t

    # --- per-bay area-time cumulative relaxation -----------------------------
    for j in range(n_bays):
        cap_j = max(1, int(prob.bays[j].W * prob.bays[j].H * rho))
        ivs, dems = [], []
        for bs in prob.blocks:
            if (bs.bid, j) not in x:
                continue
            dem = max(1, min(int(round(bs.min_area)), cap_j))
            iv = m.NewOptionalIntervalVar(entry[bs.bid], bs.P,
                                          entry[bs.bid] + bs.P, x[(bs.bid, j)],
                                          f"iv_{bs.bid}_{j}")
            ivs.append(iv)
            dems.append(dem)
        if ivs:
            m.AddCumulative(ivs, dems, cap_j)

    # --- z2 workload imbalance (weighted load per bay, max - min) ------------
    z2 = None
    if n_bays >= 2:
        U = [max(1, int(round(prob.bays[j].u * _S))) for j in range(n_bays)]
        sum_wl_u = sum(bs.workload for bs in prob.blocks) * max(U) + 1
        wl = []
        for j in range(n_bays):
            v = m.NewIntVar(0, sum_wl_u, f"wl_{j}")
            terms = [bs.workload * U[j] * x[(bs.bid, j)]
                     for bs in prob.blocks if (bs.bid, j) in x]
            m.Add(v == sum(terms) if terms else v == 0)
            wl.append(v)
        hi = m.NewIntVar(0, sum_wl_u, "hi")
        lo = m.NewIntVar(0, sum_wl_u, "lo")
        m.AddMaxEquality(hi, wl)
        m.AddMinEquality(lo, wl)
        z2 = m.NewIntVar(0, sum_wl_u, "z2")
        m.Add(z2 == hi - lo)

    # --- z3 preference penalty ----------------------------------------------
    pref_terms = []
    for bs in prob.blocks:
        for j in bs.fitting_bays:
            pen = bs.max_pref - (bs.prefs[j] if j < len(bs.prefs) else 0)
            if pen > 0:
                pref_terms.append(pen * x[(bs.bid, j)])

    # --- cuts ----------------------------------------------------------------
    for (jj, bset) in nogoods:
        terms = [x[(b, jj)] for b in bset if (b, jj) in x]
        if terms:
            m.Add(sum(terms) <= len(terms) - 1)
    for (jj, bset, kmax) in card_cuts:
        terms = [x[(b, jj)] for b in bset if (b, jj) in x]
        if terms:
            m.Add(sum(terms) <= max(0, min(kmax, len(terms) - 1)))

    # --- objective (unit-consistent with the grader) ------------------------
    c1 = max(1, int(round(prob.w1)))
    c2 = max(1, int(round(prob.w2)))
    c3 = max(1, int(round(prob.w3)))
    obj = c1 * _S * sum(tard[bs.bid] for bs in prob.blocks)
    if z2 is not None:
        obj = obj + c2 * z2                       # z2 already carries the 1000x via U
    if pref_terms:
        obj = obj + c3 * _S * sum(pref_terms)
    m.Minimize(obj)

    if hint:
        for bs in prob.blocks:
            j = hint.get(bs.bid)
            if j is not None and (bs.bid, j) in x:
                m.AddHint(x[(bs.bid, j)], 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, float(time_budget))
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None

    assign: dict[int, int] = {}
    for bs in prob.blocks:
        for j in bs.fitting_bays:
            if (bs.bid, j) in x and solver.Value(x[(bs.bid, j)]) == 1:
                assign[bs.bid] = j
                break
    relaxed_bay_z1: dict[int, int] = {j: 0 for j in range(n_bays)}
    for bs in prob.blocks:
        j = assign.get(bs.bid)
        if j is not None:
            relaxed_bay_z1[j] += int(solver.Value(tard[bs.bid]))
    return assign, relaxed_bay_z1
