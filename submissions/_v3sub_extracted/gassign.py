"""Global bay-assignment solver: T2 (assignment + cumulative area-time
relaxation) fused with T6 (Logic-Based Benders Decomposition).

Motivation
----------
The shipping assignment engine (``myalgorithm._cpsat_assignment``) optimises
only z2 (workload imbalance) + z3 (preference) -- it is *z1-blind*.  It can
therefore hand a bay more blocks than that bay can TEMPORALLY hold, and the
crane-aware decoder then serialises them, producing tardiness (z1) the
assignment never saw.

This engine makes assignment z1-aware:

  T2 (master, relaxation):  CP-SAT assignment x[b,j] PLUS per-bay
      AddCumulative over [release, release+P] windows with demand = block
      footprint area and capacity = floor(W*H*RHO).  Area-sum <= capacity is
      a *necessary* (not sufficient) condition for 2D+crane packing, so the
      master is a relaxation that already prunes temporally-overpacked bays.
      Objective mirrors the real checker: round(w1)*Sigma tard + round(w2)*z2
      + round(w3)*z3 (weight-adaptive).

  T6 (LBBD, verification):  the master is a relaxation, so each candidate bay
      set is VERIFIED geometrically by the proven crane-aware decoder
      ``fastfloor._fixed_time_decode``.  A bay that cannot place its set
      (decode -> None) yields a no-good cut ``Sigma_{b in set} x[b,j] <=
      |set|-1`` and the master is re-solved.  Loop until every bay decodes OR
      deadline OR max iterations.

The whole thing is a GATED best-of candidate in ``myalgorithm.algorithm``:
adopted only if check_feasibility passes AND objective strictly improves,
wrapped in try/except.  It can NEVER cause -1; worst case it is discarded.
``algorithm`` here NEVER raises and is deadline-bounded.
"""

from __future__ import annotations

import math
import os
import time


# ---------------------------------------------------------------------------
# Env helpers (inlined to avoid importing myalgorithm at module load -> no
# circular import; myalgorithm imports nothing from us, but we import its
# decoders LAZILY inside functions so a partial-init module is never a problem).
# ---------------------------------------------------------------------------
def _env_on(name: str, default: bool) -> bool:
    try:
        v = os.environ.get(name, "").strip().lower()
        if not v:
            return default
        return v not in ("0", "false", "off", "no")
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return float(v)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = os.environ.get(name, "").strip()
        if not v:
            return default
        return int(float(v))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Geometry helpers (self-contained; mirror baseline_greedy._block_bbox so we do
# not depend on import order, but fall back to it if available).
# ---------------------------------------------------------------------------
def _bbox_area_min(blk: dict) -> int:
    """Smallest bbox footprint area over all orientations (conservative demand
    for the area-time cumulative -- the block needs at least this much
    concurrent area in whatever bay it lands)."""
    try:
        from baseline_greedy import _block_bbox  # lazy, avoids import-order issues
    except Exception:
        _block_bbox = None
    best = None
    shapes = blk.get("shape", []) or []
    for oi in range(len(shapes)):
        if _block_bbox is not None:
            bb = _block_bbox(blk, oi)
            a = (bb[2] - bb[0]) * (bb[3] - bb[1])
        else:
            verts = [v for l in shapes[oi].get("layers", []) for v in l]
            if not verts:
                continue
            xs = [p[0] for p in verts]
            ys = [p[1] for p in verts]
            a = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if best is None or a < best:
            best = a
    return max(1, int(round(best if best is not None else 1)))


def _max_layer_count(blk: dict) -> int:
    """Max number of stacked layers across the block's orientations.  A block with
    >1 layer occupies multiple vertical levels -> its crane access (j>=k) is far
    more contended, so a bay holding many such blocks packs less efficiently."""
    best = 1
    for sh in blk.get("shape", []) or []:
        n = len([l for l in sh.get("layers", []) if l])
        if n > best:
            best = n
    return best


def _time_overlap_clique(ids, blocks_data):
    """Return the largest set of blocks in ``ids`` whose [release, due] windows
    all overlap a common instant (a temporal clique).  These are exactly the
    blocks that contend for the bay's single crane at the same time -> the ones
    a tardy-aware cut must cap.  O(n log n) sweep over window endpoints.

    Using a clique (rather than the whole assigned set) makes the cut generalize:
    it forbids over-stuffing any time slice, not one exact combination."""
    if len(ids) < 2:
        return list(ids)
    wins = []
    for b in ids:
        r = int(blocks_data[b]["release_time"])
        d = int(blocks_data[b]["due_date"])
        # use due as the window end (the latest a block could still be present
        # before it is tardy); guard d>=r.
        wins.append((b, r, max(r + 1, d)))
    # Candidate instants = release times; pick the one covered by the most.
    best_set = list(ids)
    best_cnt = 1
    rels = sorted({r for (_b, r, _d) in wins})
    for t in rels:
        cur = [b for (b, r, d) in wins if r <= t < d]
        if len(cur) > best_cnt:
            best_cnt = len(cur)
            best_set = cur
    return best_set


def _adaptive_rho(prob_info, n_bays, n_blocks, base):
    """Fix 2: tighten the area-time cumulative capacity (RHO) when bays are dense
    (many blocks per bay) or multi-layer.  RHO=0.85 is too loose for set2-style
    instances (big multi-layer bays) -- the area-sum<=cap relaxation then never
    bites, so the master temporally over-packs a bay and the decoder pays in z1.

    Rule:  rho = base - k1*max(0, bpb-bpb0)/bpb0 - k2*(layer_frac)
    where bpb = avg blocks/bay, bpb0 = a "loose" reference density, layer_frac =
    fraction of blocks that are multi-layer.  Clamped to [0.55, 0.85]."""
    try:
        blocks = prob_info["blocks"]
        bpb = n_blocks / max(1, n_bays)
        multi = sum(1 for b in range(n_blocks)
                    if _max_layer_count(blocks[b]) > 1)
        layer_frac = multi / max(1, n_blocks)
        bpb0 = 4.0   # reference: <=4 blocks/bay is "loose"
        k1 = 0.12    # per unit of relative excess density
        k2 = 0.20    # full multi-layer pulls rho down by up to 0.20
        rho = base
        rho -= k1 * max(0.0, (bpb - bpb0) / bpb0)
        rho -= k2 * layer_frac
        return max(0.55, min(0.85, rho))
    except Exception:
        return max(0.55, min(0.85, base))


# ---------------------------------------------------------------------------
# Master: T2 assignment + cumulative area-time relaxation, with T6 no-good cuts.
# ---------------------------------------------------------------------------
def _solve_master(prob_info, bays, feasible_bays, bay_u, bb_area, rho,
                  time_budget, workers, nogoods, card_cuts=None,
                  hint=None, diag=None, dg_w_override=None):
    """Solve the area-time-relaxed assignment master subject to the accumulated
    cuts.  Returns ``(assign, relaxed_bay_z1)`` or ``(None, None)``.

    ``assign`` is a list block->bay; ``relaxed_bay_z1[j]`` is the master's
    (relaxed) tardiness booked to bay j -- used by the tardy-aware LBBD cut.

    ``nogoods`` is a list of (bay_j, frozenset_of_blocks) -- each adds
    ``Sigma_{b in set} x[b,j] <= |set|-1`` (forbid that exact overloaded set in
    that bay).

    ``card_cuts`` (Fix 3, generalizing) is a list of (bay_j, frozenset_blocks,
    kmax) -- each adds ``Sigma_{b in set} x[b,j] <= kmax`` (allow at most kmax of
    a time-overlapping block set in bay j).  This bounds how many mutually
    time-conflicting blocks the master may pile into one bay's crane, which is
    the real source of decode-feasible-but-tardy degeneration.
    """
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    blocks = prob_info["blocks"]
    n_blocks = len(blocks)
    n_bays = len(bays)
    if n_bays < 1 or n_blocks == 0:
        return None

    w = prob_info.get("weights", {})
    w1 = w.get("w1", 1.0)
    w2 = w.get("w2", 1.0)
    w3 = w.get("w3", 1.0)

    m = cp_model.CpModel()

    # Assignment vars.
    x = {}
    for b in range(n_blocks):
        fb = feasible_bays[b] or list(range(n_bays))
        for j in fb:
            x[b, j] = m.NewBoolVar(f"x_{b}_{j}")
        m.Add(sum(x[b, j] for j in fb) == 1)

    # --- Horizon + entry/tard (the z1-aware part) --------------------------
    P = [int(blocks[b]["processing_time"]) for b in range(n_blocks)]
    R = [int(blocks[b]["release_time"]) for b in range(n_blocks)]
    D = [int(blocks[b]["due_date"]) for b in range(n_blocks)]
    H = max(D) + sum(P) + 1  # safe horizon

    entry = [m.NewIntVar(R[b], H, f"e_{b}") for b in range(n_blocks)]
    tard = [m.NewIntVar(0, H, f"t_{b}") for b in range(n_blocks)]
    for b in range(n_blocks):
        # tard[b] >= entry[b] + P[b] - D[b]  ;  tard[b] >= 0 (var domain)
        m.Add(tard[b] >= entry[b] + P[b] - D[b])

    # --- Per-bay cumulative area-time relaxation ---------------------------
    # iv[b,j] present iff x[b,j]; window [entry[b], entry[b]+P[b]); demand =
    # bbox area; capacity = floor(W_j*H_j*rho).  area-sum<=cap is necessary.
    for j in range(n_bays):
        cap_j = max(1, int(bays[j].width * bays[j].height * rho))
        ivs = []
        dems = []
        for b in range(n_blocks):
            if (b, j) not in x:
                continue
            dem = min(bb_area[b], cap_j)  # clamp so a single block never > cap
            iv = m.NewOptionalIntervalVar(entry[b], P[b], entry[b] + P[b],
                                          x[b, j], f"iv_{b}_{j}")
            ivs.append(iv)
            dems.append(dem)
        if ivs:
            m.AddCumulative(ivs, dems, cap_j)

    # --- z2 (imbalance): mirror _cpsat_assignment's max-min weighted-load ---
    U = [int(round(bay_u[j] * 1000)) for j in range(n_bays)]
    Umax = max(U) if U else 1
    wsum = sum(int(round(blocks[b]["workload"])) for b in range(n_blocks))
    wl = []
    for j in range(n_bays):
        terms = []
        for b in range(n_blocks):
            if (b, j) in x:
                terms.append(int(round(blocks[b]["workload"])) * U[j] * x[b, j])
        v = m.NewIntVar(0, (wsum + 1) * (Umax + 1), f"wl_{j}")
        m.Add(v == sum(terms))
        wl.append(v)
    if n_bays >= 2:
        hi = m.NewIntVar(0, (wsum + 1) * (Umax + 1), "hi")
        lo = m.NewIntVar(0, (wsum + 1) * (Umax + 1), "lo")
        m.AddMaxEquality(hi, wl)
        m.AddMinEquality(lo, wl)
        z2 = m.NewIntVar(0, (wsum + 1) * (Umax + 1), "z2")
        m.Add(z2 == hi - lo)
    else:
        z2 = m.NewConstant(0)

    # --- z3 (preference) ---------------------------------------------------
    pref_terms = []
    for b in range(n_blocks):
        prefs = blocks[b]["bay_preferences"]
        s_max = max(prefs)
        for j in feasible_bays[b] or list(range(n_bays)):
            if (b, j) not in x:
                continue
            pen = s_max - prefs[j]
            if pen:
                pref_terms.append(pen * x[b, j])

    # --- No-good cuts (T6, place-fail) -------------------------------------
    for (jj, bset) in nogoods:
        terms = [x[b, jj] for b in bset if (b, jj) in x]
        if terms:
            m.Add(sum(terms) <= len(terms) - 1)

    # --- Cardinality cuts (Fix 3, tardy-aware) -----------------------------
    # Bound the number of mutually time-overlapping blocks bay j may hold.
    for (jj, bset, kmax) in (card_cuts or []):
        terms = [x[b, jj] for b in bset if (b, jj) in x]
        if terms:
            m.Add(sum(terms) <= max(0, min(int(kmax), len(terms) - 1)))

    # --- Departure-time grouping (OGC_GASSIGN_DEPGROUP_W, default 0 = OFF) --
    # Block-Relocation / Borgman 2010 insight (research 2026-06-17, §5): keeping
    # blocks whose scheduled DEPARTURES (due dates) are CLOSE in the same bay
    # reduces crane-access conflicts -- a block needing the crane at time T is
    # less likely to be buried under a much-later-leaving block, so the decoder
    # serialises fewer of them (lower realised z1) AND fewer must be spilled off
    # their preferred bay (lower z3).  We penalise the per-bay SPREAD of due
    # dates (hi-lo, mirroring the z2 max-min idiom) for non-trivial bays.
    #
    # This is a soft TIE-BREAKER: it must NOT distort the checker-matched
    # w1:w2:w3 ratio, so its coefficient is a SMALL fraction (dg_w, ~0.01-0.1)
    # of the z1 basis (c1*_S).  It only steers among assignments the main
    # objective rates ~equal toward less-conflicting (tighter-departure) bays.
    # Because myalgorithm keeps the best ACTUAL decode (best_true_z1) and wraps
    # gassign in a best-of guard, a mis-steer can never regress the shipped sol.
    depgroup_terms = []
    dg_w = (dg_w_override if dg_w_override is not None
            else _env_float("OGC_GASSIGN_DEPGROUP_W", 0.0))
    if dg_w > 0.0:
        # OGC_GASSIGN_DEPGROUP_KEY: "due" (default) | "mid" (release..due midpoint)
        # | "exit" (release+P, the natural earliest exit).  "mid"/"exit" weight a
        # block's actual presence window, not just its deadline (develop knob).
        dg_key = os.environ.get("OGC_GASSIGN_DEPGROUP_KEY", "due").strip().lower()
        def _dep_val(b):
            if dg_key == "mid":
                return (R[b] + max(R[b] + P[b], D[b])) // 2
            if dg_key == "exit":
                return R[b] + P[b]
            return D[b]
        depv = [int(_dep_val(b)) for b in range(n_blocks)]
        maxv = max(depv) if depv else 1
        for j in range(n_bays):
            xbj = [(b, x[b, j]) for b in range(n_blocks) if (b, j) in x]
            if len(xbj) < 2:
                continue
            hi = m.NewIntVar(0, maxv, f"dgh_{j}")
            lo = m.NewIntVar(0, maxv, f"dgl_{j}")
            for (b, xv) in xbj:
                m.Add(hi >= depv[b]).OnlyEnforceIf(xv)
                m.Add(lo <= depv[b]).OnlyEnforceIf(xv)
            sp = m.NewIntVar(0, maxv, f"dgs_{j}")
            m.Add(sp >= hi - lo)
            depgroup_terms.append(sp)

    # --- Objective: weight-adaptive, UNIT-CONSISTENT with the checker -------
    # CRITICAL invariant (Fix 1): the master's relative weighting of (z1,z2,z3)
    # must equal the checker's w1:w2:w3.  The three integer terms below carry
    # DIFFERENT internal scales, so we lift them ALL to a common 1000x basis
    # before applying the (rounded) checker weights:
    #   * z2 internally = 1000 * (real z2)   [U[j] = round(bay_u*1000)]
    #   * z3 (pref_sum) is the RAW penalty   -> multiply by 1000
    #   * z1 (sum tard) is in RAW time units -> multiply by 1000  (was *1!)
    # The earlier *1 on z1 made the master under-weight tardiness by 1000x vs
    # the checker -> it produced tardy "optimal" assignments the decoder then
    # serialised into huge z1.  With all three at 1000x, the coefficient ratio
    # c1*z1 : c2*z2 : c3*z3 == round(w1) : round(w2) : round(w3) == checker.
    _S = 1000  # common scale; every z is expressed in (real z) * _S units
    # Master z1<->z3 bias (2026-06-18): the area-time relaxation OVER-estimates how
    # much spilling reduces TRUE z1 (the geometric decode can't realise it), so the
    # master OVER-spills (set2 diag: pays 14M z3 to save 11M z1 = net-bad vs comp).
    # C3_MULT>1 (or C1_MULT<1) makes spilling LESS attractive in the master -> keeps
    # blocks on preferred bays -> lower z3.  Default 1.0 = checker-matched (Fix 1),
    # byte-identical.  Gated experiment; validate on full set (total obj).
    # ADOPTED default 2.0 (2026-06-18): full set2 @T240 271.93M vs 282.64M baseline
    # (−3.79%, BEATS competitor 279.82M by 7.89M); set1 net −1.96%; feasible 40/40,
    # never −1.  Counteracts the relaxation's z1-overestimate so the master spills
    # less → lower z3 at ~no z1 cost.  Revert with OGC_GASSIGN_C3_MULT=1.0.
    c1 = max(1, int(round(w1 * _env_float("OGC_GASSIGN_C1_MULT", 1.0))))
    c2 = max(1, int(round(w2)))
    c3 = max(1, int(round(w3 * _env_float("OGC_GASSIGN_C3_MULT", 2.0))))
    obj = c1 * _S * sum(tard)          # z1 lifted to 1000x basis (Fix 1)
    obj += c2 * z2                      # z2 already 1000x via U scaling
    if pref_terms:
        obj += c3 * _S * sum(pref_terms)  # z3 lifted to 1000x basis
    # Departure-grouping tie-breaker: coefficient = dg_w * (z1 basis).  dg_w is
    # a small fraction so per-unit-spread cost stays well below per-unit-tard
    # cost; the term only breaks ties toward decode-friendly (tight-departure)
    # assignments.  coef>=1 so a positive dg_w always has SOME effect.
    if depgroup_terms and dg_w > 0.0:
        dg_coef = max(1, int(round(c1 * _S * dg_w)))
        obj += dg_coef * sum(depgroup_terms)
    m.Minimize(obj)

    # --- Warm-start hint ---------------------------------------------------
    if hint is not None:
        try:
            for b in range(n_blocks):
                jb = hint[b] if b < len(hint) else -1
                if (b, jb) in x:
                    m.AddHint(x[b, jb], 1)
        except Exception:
            pass

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, float(time_budget))
    solver.parameters.num_search_workers = max(1, int(workers))
    try:
        solver.parameters.random_seed = _env_int("OGC_GASSIGN_SEED", 20260616)
    except Exception:
        pass
    status = solver.Solve(m)
    if diag is not None:
        try:
            diag["status"] = solver.StatusName(status)
            diag["obj"] = solver.ObjectiveValue()
            diag["wall"] = round(solver.WallTime(), 3)
        except Exception:
            pass
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None
    assign = [-1] * n_blocks
    for b in range(n_blocks):
        for j in feasible_bays[b] or list(range(n_bays)):
            if (b, j) in x and solver.Value(x[b, j]) == 1:
                assign[b] = j
                break
    if any(a < 0 for a in assign):
        return None, None
    # Relaxed per-bay tardiness (the master's claim) for the tardy-aware cut.
    relaxed_bay_z1 = [0.0] * n_bays
    try:
        for b in range(n_blocks):
            tb = solver.Value(tard[b])
            if tb > 0:
                relaxed_bay_z1[assign[b]] += tb
    except Exception:
        relaxed_bay_z1 = [0.0] * n_bays
    return assign, relaxed_bay_z1


# ---------------------------------------------------------------------------
# Per-bay verification via the proven crane-aware BL decoder (the LBBD oracle).
# ---------------------------------------------------------------------------
def _bay_z1_of(res, blocks_data):
    """Total tardiness booked to one bay's decode result (decoder exit vs due)."""
    z = 0.0
    for b, rec in res.items():
        z += max(0.0, int(rec["exit_time"]) - int(blocks_data[b]["due_date"]))
    return z


def _windowed_bay(prob_info, bay_idx, ids, blocks_data, ff_res, per_bay):
    """[A] Subproblem escalation: re-decode ONE bay with the STRONGER windowed
    CP-SAT packer best-of {fixed-orient, 4D-orient} + per-bay timing (relayout's
    packers), seeded by fastfloor's orientations.  Returns a result dict
    {block: record} in fastfloor's exact record format IFF its bay z1 strictly
    beats fastfloor's, else None.  NEVER raises (caller wraps in try/except)."""
    import relayout as _rl
    orient_of = {b: int(ff_res[b]["orient_idx"]) for b in ids}
    base_z = _bay_z1_of(ff_res, blocks_data)
    # per_bay is a TOTAL budget: split between the two packers; pack_windowed
    # already minimises tardiness JOINTLY with placement (its CP-SAT entry vars
    # ARE the timing), so we read z1 from the packer output directly -- NO extra
    # solve_timing pass (that doubled the cost and blew the wall budget).
    half = max(1.0, per_bay * 0.5)
    bs = max(1.0, min(5.0, half))
    l1 = l2 = None
    try:
        l1 = _rl.pack_windowed_cpsat(prob_info, bay_idx, ids,
                                     time.monotonic() + half, orient_of,
                                     K=30, batch_s=bs)
    except Exception:
        l1 = None
    try:
        l2 = _rl.pack_windowed_4d(prob_info, bay_idx, ids, half, orient_of,
                                  K=18, batch_s=bs, ncand=2)
    except Exception:
        l2 = None
    best_lay = None
    best_z = base_z
    for lay in (l1, l2):
        if lay is None:
            continue
        z = sum(max(0, int(lay[b][4]) - int(blocks_data[b]["due_date"]))
                for b in ids)
        if z < best_z:
            best_z, best_lay = z, lay
    if best_lay is None:
        return None
    return {b: {"block_id": b, "bay_id": bay_idx,
                "x": int(best_lay[b][0]), "y": int(best_lay[b][1]),
                "orient_idx": int(best_lay[b][2]),
                "entry_time": int(best_lay[b][3]),
                "exit_time": int(best_lay[b][4])} for b in ids}


def _decode_bay(prob_info, bay, bay_idx, ids, blocks_data, deadline,
                esc_state=None, n_max=999999):
    """Run fastfloor._fixed_time_decode on one bay's assigned block set.
    Returns (result | None, ft_stats).  result == None => infeasible set.

    Well-placed race (OGC_GASSIGN_WELLPLACED, default OFF; research 2026-06-17
    §5): the default F0 order (entry asc, area desc) can place a late-due block
    before an early-due one, BURYING the urgent block so it must shift to a later
    placed-exit slot (tardiness).  Block-Relocation's "well-placed" invariant
    says urgent (early-due) blocks should claim space first.  When enabled we
    RACE F0 against a due-aware order (default F2 = due asc, EDD) and keep the
    decode with lower bay tardiness.  Costs one extra decode per bay -> gated;
    a tie or worse alt is simply discarded, so it can only help."""
    from fastfloor import _fixed_time_decode  # lazy import (decoder)
    keys = ["F0"]
    if _env_on("OGC_GASSIGN_WELLPLACED", False):
        for k in os.environ.get("OGC_GASSIGN_WP_KEYS", "F2").split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
    if len(keys) == 1:
        best, best_stats = _fixed_time_decode(bay, bay_idx, ids, blocks_data,
                                              deadline, order_key="F0")
    else:
        best = None
        best_stats = None
        best_z = math.inf
        for k in keys:
            if time.monotonic() >= deadline - 0.3:
                break
            res, ft = _fixed_time_decode(bay, bay_idx, ids, blocks_data,
                                         deadline, order_key=k)
            if res is None:
                if best_stats is None:
                    best_stats = ft  # remember a fail's stats for the cut path
                continue
            z = _bay_z1_of(res, blocks_data)
            if z < best_z:
                best_z, best, best_stats = z, res, ft
            if best_z <= 0.0:
                break  # zero tardiness for this bay -> cannot improve
    # [A] LBBD SUBPROBLEM escalation (OGC_GASSIGN_RELAYOUT_DECODER, default OFF;
    # user design 2026-06-19 "벤더스컷 하위문제를 relayout이").  fastfloor stays the
    # FEASIBILITY oracle (fast + reliable -> no-good cuts never corrupted); when a
    # bay it ALREADY packed is still TARDY, escalate to the stronger windowed
    # CP-SAT decode (only refines an already-feasible bay).  A lower true bay-z1
    # -> the tardy cardinality cut (caller) fires LESS -> the master spills LESS
    # -> attacks the set2 z3 over-spill at the Benders subproblem.  Bounded by
    # `deadline` (-1-safe) + a per-bay budget; a windowed timeout just keeps
    # fastfloor's layout.  Previously FALSIFIED as a wholesale in-loop ALNS
    # decoder (cut coupling + noise); this variant escalates ONLY tardy bays and
    # never overrides the feasibility verdict, so the cuts stay fastfloor-clean.
    if (best is not None and _env_on("OGC_GASSIGN_RELAYOUT_DECODER", False)):
        try:
            bz = _bay_z1_of(best, blocks_data)
            z1min = _env_float("OGC_GASSIGN_DECODER_Z1MIN", 1.0)
            per_bay = max(1.0, _env_float("OGC_GASSIGN_DECODER_PERBAY_S", 4.0))
            # Hard -1 guards: per-call deadline, a per-bay SIZE cap (windowed
            # CP-SAT model-build cost explodes on big bays -> n>n_max skipped),
            # and a shared GLOBAL escalation-time cap (esc_state=[spent, cap]) so
            # the cumulative windowed time across all bays/iterations can never
            # starve the master or blow the wall (= -1 on the eval server).
            _esc_ok = (esc_state is None or esc_state[0] < esc_state[1])
            if (bz > z1min and 2 <= len(ids) <= n_max and _esc_ok
                    and time.monotonic() < deadline - per_bay - 0.5):
                _t_esc = time.monotonic()
                wres = _windowed_bay(prob_info, bay_idx, ids, blocks_data,
                                     best, per_bay)
                if esc_state is not None:
                    esc_state[0] += time.monotonic() - _t_esc
                if wres is not None and _bay_z1_of(wres, blocks_data) < bz:
                    if _env_on("OGC_GASSIGN_DECODER_DIAG", False):
                        import sys as _sys
                        print("[GASSIGN-DECODER] bay=%d n=%d z1 %.0f -> %.0f"
                              % (bay_idx, len(ids), bz,
                                 _bay_z1_of(wres, blocks_data)),
                              file=_sys.stderr, flush=True)
                    best = wres
        except Exception:
            pass
    return best, best_stats


def _obj_of_results(results, prob_info, bays, bay_u):
    """Approx checker objective (w1*z1 + w2*z2 + w3*z3) from DECODED per-bay
    results -- used ONLY to rank two gassign candidates (base vs depgroup).
    Mirrors _solve_master's z formulas (Fix-1 unit basis); it is a ranking
    surrogate, not a substitute for utils.check_feasibility."""
    blocks = prob_info["blocks"]
    w = prob_info.get("weights", {})
    w1 = w.get("w1", 1.0)
    w2 = w.get("w2", 1.0)
    w3 = w.get("w3", 1.0)
    n_bays = len(bays)
    z1 = 0.0
    z3 = 0.0
    wl = [0.0] * n_bays
    for j, by_id in results.items():
        for b, rec in by_id.items():
            z1 += max(0.0, int(rec["exit_time"]) - int(blocks[b]["due_date"]))
            wl[j] += float(blocks[b]["workload"]) * bay_u[j]
            prefs = blocks[b]["bay_preferences"]
            z3 += max(prefs) - prefs[j]
    z2 = (max(wl) - min(wl)) if n_bays >= 2 else 0.0
    return w1 * z1 + w2 * z2 + w3 * z3


def _lbbd(prob_info, bays, feasible_bays, bay_u, bb_area, rho, hint,
          workers, max_iters, master_frac, tardy_slack, dg_w, deadline,
          esc_state=None, n_max=999999):
    """One LBBD master<->decoder solve at a given departure-grouping weight
    ``dg_w`` (0 = off).  Returns best_results (dict bay_idx -> {block: record})
    or None.  Deadline-bounded; the master gets master_frac of the REMAINING
    budget on the first iteration and a smaller slice on re-solves, so calling
    this twice (base then depgroup) lets the second pass consume only whatever
    budget the first pass left unused."""
    blocks_data = prob_info["blocks"]
    n_blocks = len(blocks_data)
    n_bays = len(bays)
    nogoods: list[tuple[int, frozenset]] = []
    card_cuts: list[tuple[int, frozenset, int]] = []
    best_results = None
    best_true_z1 = math.inf
    for it in range(max_iters):
        now = time.monotonic()
        remaining = deadline - now
        if remaining <= 1.0:
            break
        mbudget = remaining * (master_frac if it == 0 else 0.35)
        mbudget = max(1.0, min(mbudget, remaining - 0.5))

        assign, relaxed_bay_z1 = _solve_master(
            prob_info, bays, feasible_bays, bay_u, bb_area, rho, mbudget,
            workers, nogoods, card_cuts=card_cuts, hint=hint,
            dg_w_override=dg_w)
        if assign is None:
            break
        if relaxed_bay_z1 is None:
            relaxed_bay_z1 = [0.0] * n_bays

        per_bay_ids: dict[int, list[int]] = {j: [] for j in range(n_bays)}
        for b in range(n_blocks):
            per_bay_ids[assign[b]].append(b)

        results: dict[int, dict] = {}
        new_cuts = 0
        tardy_cuts = 0
        decode_complete = True
        true_z1 = 0.0
        for j in range(n_bays):
            ids = per_bay_ids[j]
            if not ids:
                results[j] = {}
                continue
            if time.monotonic() >= deadline - 0.5:
                decode_complete = False
                break
            res, _ft = _decode_bay(prob_info, bays[j], j, ids, blocks_data,
                                   deadline, esc_state=esc_state, n_max=n_max)
            if res is None:
                nogoods.append((j, frozenset(ids)))
                new_cuts += 1
                decode_complete = False
            else:
                results[j] = res
                bz1 = 0.0
                for b, rec in res.items():
                    bz1 += max(0.0, int(rec["exit_time"])
                               - int(blocks_data[b]["due_date"]))
                true_z1 += bz1
                if bz1 > relaxed_bay_z1[j] + tardy_slack:
                    oset = _time_overlap_clique(ids, blocks_data)
                    if len(oset) >= 2:
                        kmax = max(1, len(oset) - 1)
                        card_cuts.append((j, frozenset(oset), kmax))
                        tardy_cuts += 1

        if decode_complete and true_z1 < best_true_z1:
            best_true_z1 = true_z1
            best_results = results

        if decode_complete and tardy_cuts == 0:
            break
        if new_cuts == 0 and tardy_cuts == 0:
            break
    return best_results


def _second_b2b3_pass(prob_info, bays, sol, deadline):
    """User's B2<->B3 coordinate-descent (2026-06-19).  The current decode is
    B2 (fastfloor greedy place by entry-time order) -> B3 (CP-SAT timing on the
    fixed positions).  This adds the next half-cycle: RE-RUN B2 with the
    placement ORDER set to B3's OPTIMISED entry-time order, then B3 again.

    Why ORDER (not target times): B2 (`_fixed_time_decode`) always starts each
    block at entry=R and only delays on conflict -- it IGNORES external target
    times (that 'entry=R reset' is what made naive B2<->B3 looping ping-pong).
    But B2 DOES honour an explicit placement-order list, so we feed B3's
    information through the ORDER: blocks B3 wants early are placed first -> they
    claim the good positions -> the following B3 can reach a lower tardiness.

    Per-bay: only TARDY bays are re-decoded (z1=0 bays are already optimal and
    kept as-is); the full layout is then re-timed by B3 and returned as ONE
    candidate sol.  Same bay assignment -> Z2/Z3 invariant, only Z1 moves, so the
    caller's objective gate reduces to a z1 gate (never worse).  Cheap: fastfloor
    is ms/bay and there is a single extra B3 CP-SAT pass.  Returns a sol or None."""
    from fastfloor import _fixed_time_decode
    from baseline_greedy import _build_operations
    import solver_orig as _ma
    blocks = prob_info["blocks"]
    cur = {}
    for ts, ops in sol["operations"].items():
        t = int(ts)
        for op in ops:
            b = op["block_id"]; d = cur.setdefault(b, {})
            if op["type"] == "ENTRY":
                d["bay"] = op["bay_id"]; d["entry"] = t
                d["x"] = op["x"]; d["y"] = op["y"]; d["orient"] = op["orient_idx"]
            else:
                d["exit"] = t

    def _orig(b):
        d = cur[b]
        return {"block_id": b, "bay_id": d["bay"], "x": d["x"], "y": d["y"],
                "orient_idx": d["orient"], "entry_time": d["entry"],
                "exit_time": d["exit"]}

    byb = {}
    for b, d in cur.items():
        byb.setdefault(d["bay"], []).append(b)
    new_results = {}
    for j, ids in byb.items():
        z1 = sum(max(0, cur[b]["exit"] - int(blocks[b]["due_date"])) for b in ids)
        if z1 <= 0 or len(ids) < 2 or time.monotonic() >= deadline - 1.0:
            new_results[j] = {b: _orig(b) for b in ids}
            continue
        # B2 RE-DECODE with order = B3-optimised entry-time order
        order = sorted(ids, key=lambda b: (cur[b]["entry"], cur[b]["exit"]))
        res, _ft = _fixed_time_decode(bays[j], j, order, blocks, deadline,
                                      order_key=order)
        new_results[j] = res if res is not None else {b: _orig(b) for b in ids}
    # B3 re-timing on the re-decoded layout (returns a FULL sol over all bays)
    polished = _ma._cpsat_bay_timing_verified(prob_info, bays, new_results,
                                              deadline=deadline)
    if polished is not None:
        return polished
    flat = [rec for by in new_results.values() for rec in by.values()]
    return {"operations": _build_operations(flat)}


# ---------------------------------------------------------------------------
# Public entrypoint.
# ---------------------------------------------------------------------------
def algorithm(prob_info: dict, timelimit: float) -> dict | None:
    """Global T2(cumulative area-time)+T6(LBBD) assignment, then per-bay decode.

    Returns a feasible solution dict {"operations":{...}} or None on failure.
    NEVER raises; deadline-bounded by ``timelimit``.

    Env flags (all default to ship-safe values; the eval server sets none):
      OGC_GASSIGN_RHO     float (manual override) -- area-time packing-efficiency
                          factor; cumulative capacity = floor(W*H*RHO).  When
                          UNSET, RHO is derived adaptively (see below).
      OGC_GASSIGN_RHO_ADAPT bool (default ON)  -- when no manual RHO is set,
                          tighten RHO from a 0.85 base toward 0.55 for dense /
                          multi-layer (set2-style) bays so the area-time
                          cumulative actually limits temporal over-packing.
      OGC_GASSIGN_WORKERS int   (default 4)    -- CP-SAT num_search_workers.
      OGC_GASSIGN_ITERS   int   (default 6)    -- max LBBD master<->subproblem
                          iterations.
      OGC_GASSIGN_TARDY_SLACK float (default 1.0) -- a bay whose DECODED true z1
                          exceeds the master's relaxed z1 for that bay by more
                          than this gets a tardy-aware cardinality cut (Fix 3).
      OGC_GASSIGN_MASTER_FRAC float (default 0.45) -- fraction of the remaining
                          budget given to the FIRST master solve (later
                          re-solves get a smaller slice each).
      OGC_GASSIGN_TIMING  bool  (default ON)   -- polish ENTRY/EXIT on the fixed
                          layout via myalgorithm._cpsat_bay_timing_verified.
      OGC_GASSIGN_RESERVE float (default 1.5)  -- seconds held back from the
                          deadline so the caller's check_feasibility never
                          overruns the wall clock.
      OGC_GASSIGN_DEPGROUP_W float (default 0 = OFF) -- departure-time grouping
                          weight (research 2026-06-17 §5).  When >0, after the
                          base assignment a SECOND pass adds a soft per-bay
                          due-date-spread penalty (coef = W * z1-basis), run on
                          leftover budget; the better (by surrogate obj) is kept.
                          Keeps co-departing blocks together -> less burying
                          (z1) + less spill (z3).  Net set2 win on z3-over-spread
                          instances; SAFE (>= base, never None).  ~0.02-0.1.
      OGC_GASSIGN_DEPGROUP_KEY str (default "due") -- depgroup spread basis:
                          due | mid (release..due midpoint) | exit (release+P).
      OGC_GASSIGN_DG_MIN_LEFTOVER float (default 15) -- min leftover seconds
                          after the base pass required to attempt the depgroup
                          pass (so the base feasibility result is never starved).
      OGC_GASSIGN_WELLPLACED bool (default OFF) -- per-bay decode races F0 vs a
                          due-aware order (OGC_GASSIGN_WP_KEYS, default F2=EDD)
                          and keeps lower bay-tardiness (well-placed invariant).
                          Measured NEUTRAL on set2 (kept available, off).
    """
    t_start = time.monotonic()
    try:
        from utils import Bay  # cheap, no circular concern
    except Exception:
        return None

    try:
        T = max(1.0, float(timelimit))
        reserve = max(0.3, _env_float("OGC_GASSIGN_RESERVE", 1.5))
        deadline = t_start + T - reserve
        if deadline <= t_start + 0.5:
            return None

        workers = max(1, _env_int("OGC_GASSIGN_WORKERS", 4))
        max_iters = max(1, _env_int("OGC_GASSIGN_ITERS", 6))
        master_frac = _env_float("OGC_GASSIGN_MASTER_FRAC", 0.45)
        if not (0.05 <= master_frac <= 0.95):
            master_frac = 0.45

        bays_data = prob_info["bays"]
        blocks_data = prob_info["blocks"]
        n_bays = len(bays_data)
        n_blocks = len(blocks_data)
        if n_bays < 1 or n_blocks == 0:
            return None
        bays = [Bay.from_dict(d, i) for i, d in enumerate(bays_data)]

        # --- RHO: manual override wins; else adaptive (Fix 2) -------------
        # OGC_GASSIGN_RHO forces a fixed value; OGC_GASSIGN_RHO_ADAPT (default
        # on) derives a density/layer-aware value from a 0.85 base.  Default
        # base 0.85, adaptively tightened toward 0.55 for dense/multi-layer
        # (set2-style) instances so the area-time cumulative actually limits
        # how many blocks pile into one bay's time window.
        _rho_override = os.environ.get("OGC_GASSIGN_RHO", "").strip()
        if _rho_override:
            rho = _env_float("OGC_GASSIGN_RHO", 0.85)
            if not (0.05 < rho <= 2.0):
                rho = 0.85
        elif _env_on("OGC_GASSIGN_RHO_ADAPT", True):
            rho = _adaptive_rho(prob_info, n_bays, n_blocks, base=0.85)
        else:
            rho = 0.85

        # bay_u: avg_area / bay_area (mirrors _legacy_algorithm / utils).
        bay_areas = [bays_data[j]["width"] * bays_data[j]["height"]
                     for j in range(n_bays)]
        avg_area = sum(bay_areas) / n_bays if n_bays else 1.0
        bay_u = [avg_area / max(1.0, a) for a in bay_areas]

        # feasible_bays: reuse myalgorithm's exact logic (lazy import).
        try:
            import solver_orig as _ma
            feasible_bays = _ma._feasible_bays(blocks_data, bays)
        except Exception:
            feasible_bays = [list(range(n_bays)) for _ in range(n_blocks)]

        bb_area = [_bbox_area_min(blocks_data[b]) for b in range(n_blocks)]

        # Optional warm-start hint from the legacy assignment (best-effort).
        hint = None
        if _env_on("OGC_GASSIGN_HINT", True):
            try:
                hint = _ma._balanced_seed(prob_info, feasible_bays, bay_u)
            except Exception:
                hint = None

        # Tardy-cut sensitivity: fire when a bay's TRUE z1 exceeds the master's
        # RELAXED z1 for that bay by more than this slack (absolute time units).
        tardy_slack = max(0.0, _env_float("OGC_GASSIGN_TARDY_SLACK", 1.0))

        # --- Base-first departure-grouping race (research 2026-06-17 §5) ---
        # Pass 1 = NO departure-grouping (dg_w=0) -- the reliable feasibility
        # backstop = exact banked behaviour.  On easy / z3-over-spread instances
        # the LBBD converges EARLY, so budget remains; if OGC_GASSIGN_DEPGROUP_W
        # > 0 AND enough leftover time exists, pass 2 re-solves WITH departure-
        # grouping on the LEFTOVER budget and we keep whichever decodes to the
        # lower (surrogate) objective.  On HARD instances (e.g. prob_38) the base
        # pass consumes the whole budget -> pass 2 is skipped -> we always return
        # the feasible base.  Thus depgroup can NEVER make gassign return None or
        # regress below base; it only ADDS wins where it both fits and helps.
        # DEFAULT 0.05 (ON, 2026-06-17): the base-first race makes depgroup SAFE
        # (>= base per-instance, never None) so default-on is a strict win where
        # it fires; OGC_GASSIGN_DEPGROUP_W=0 restores the exact banked behaviour.
        dg_w = _env_float("OGC_GASSIGN_DEPGROUP_W", 0.05)
        # [A] LBBD subproblem escalation budget (OGC_GASSIGN_RELAYOUT_DECODER):
        # a SHARED [spent, cap] across both _lbbd passes -- total windowed time is
        # capped at ESC_FRAC of gassign's budget so the master is never starved
        # and the wall never overruns (-1-safe).  n_max skips big bays where the
        # windowed CP-SAT model-build cost is prohibitive.  Both default off-path
        # (esc_state ignored unless the DECODER env is on).
        _esc_cap = (max(0.0, _env_float("OGC_GASSIGN_DECODER_ESC_FRAC", 0.35))
                    * max(0.0, deadline - t_start))
        esc_state = [0.0, _esc_cap]
        n_max = _env_int("OGC_GASSIGN_DECODER_NMAX", 30)
        base_results = _lbbd(prob_info, bays, feasible_bays, bay_u, bb_area, rho,
                             hint, workers, max_iters, master_frac, tardy_slack,
                             dg_w=0.0, deadline=deadline,
                             esc_state=esc_state, n_max=n_max)
        best_results = base_results
        if dg_w > 0.0 and base_results is not None:
            dg_min_leftover = max(3.0,
                                  _env_float("OGC_GASSIGN_DG_MIN_LEFTOVER", 15.0))
            if deadline - time.monotonic() >= dg_min_leftover:
                dg_results = _lbbd(prob_info, bays, feasible_bays, bay_u, bb_area,
                                   rho, hint, workers, max_iters, master_frac,
                                   tardy_slack, dg_w=dg_w, deadline=deadline,
                                   esc_state=esc_state, n_max=n_max)
                if dg_results is not None:
                    try:
                        base_obj = _obj_of_results(base_results, prob_info,
                                                   bays, bay_u)
                        dg_obj = _obj_of_results(dg_results, prob_info, bays,
                                                 bay_u)
                        adopted = dg_obj < base_obj
                        if adopted:
                            best_results = dg_results
                        # Within-run, noise-free diag (OGC_GASSIGN_DG_DIAG):
                        # base vs depgroup surrogate obj on the SAME CP-SAT draw.
                        if _env_on("OGC_GASSIGN_DG_DIAG", False):
                            import sys as _sys
                            print("[GASSIGN-DG] base_obj=%.0f dg_obj=%.0f "
                                  "delta=%.0f adopted=%s leftover_ok=1"
                                  % (base_obj, dg_obj, dg_obj - base_obj,
                                     adopted), file=_sys.stderr, flush=True)
                    except Exception:
                        best_results = base_results
            elif _env_on("OGC_GASSIGN_DG_DIAG", False):
                import sys as _sys
                print("[GASSIGN-DG] depgroup SKIPPED (insufficient leftover "
                      "after base pass)", file=_sys.stderr, flush=True)

        if best_results is None:
            return None

        # --- Assemble flat record list -----------------------------------
        flat = []
        for j, by_id in best_results.items():
            for _b, rec in by_id.items():
                flat.append(rec)
        if len(flat) != n_blocks:
            return None

        # --- Optional timing polish on the FIXED layout (B3) -------------
        # When the [D] B2<->B3 second pass is on, CAP this first B3 to a FRACTION
        # of the remaining budget and reserve the rest for the re-decode+B3 pass
        # below (so the SAME total budget is split into two coordinate-descent
        # half-cycles instead of one long timing solve -- no extra budget, and the
        # gate is OFF by default so production keeps the full-budget single B3).
        _b3_deadline = deadline
        if _env_on("OGC_GASSIGN_B2B3", False):
            _b3_frac = min(0.95, max(0.3, _env_float("OGC_GASSIGN_B2B3_FRAC", 0.6)))
            _now_b3 = time.monotonic()
            _b3_deadline = _now_b3 + _b3_frac * max(0.0, deadline - _now_b3)
        sol = None
        if _env_on("OGC_GASSIGN_TIMING", True) and time.monotonic() < deadline - 1.0:
            try:
                import solver_orig as _ma
                polished = _ma._cpsat_bay_timing_verified(
                    prob_info, bays, best_results, deadline=_b3_deadline)
                if polished is not None:
                    sol = polished
            except Exception:
                sol = None

        if sol is None:
            try:
                from baseline_greedy import _build_operations
                sol = {"operations": _build_operations(flat)}
            except Exception:
                return None

        # --- [D] B2<->B3 second pass (user 2026-06-19): re-run B2 with B3's
        # optimised entry-time ORDER, then B3 again.  Runs ONLY on the LEFTOVER
        # budget after the first B3 (so it never starves the primary decode) and
        # is obj-gated (same assignment -> z1-only gate) -> never worse, never -1.
        # Cheap (fastfloor + one B3 pass), so unlike the windowed placements it
        # doesn't blow the wall.  Gated OGC_GASSIGN_B2B3 (default OFF).
        if sol is not None and _env_on("OGC_GASSIGN_B2B3", False):
            _b2b3_min = max(1.0, _env_float("OGC_GASSIGN_B2B3_MIN_S", 3.0))
            if deadline - time.monotonic() >= _b2b3_min:
                try:
                    from utils import check_feasibility as _ckf
                    _sol2 = _second_b2b3_pass(prob_info, bays, sol, deadline)
                    if _sol2 is not None:
                        _c2 = _ckf(prob_info, _sol2)
                        _c1 = _ckf(prob_info, sol)
                        if (_c2.get("feasible") and _c1.get("feasible")
                                and _c2.get("objective") is not None
                                and _c1.get("objective") is not None
                                and _c2["objective"] < _c1["objective"] - 1e-9):
                            if _env_on("OGC_GASSIGN_B2B3_DIAG", False):
                                import sys as _sys
                                print("[GASSIGN-B2B3] %.0f -> %.0f (delta %.0f)"
                                      % (_c1["objective"], _c2["objective"],
                                         _c2["objective"] - _c1["objective"]),
                                      file=_sys.stderr, flush=True)
                            sol = _sol2
                except Exception:
                    pass

        # --- [B] WINDOWED RELAYOUT final decode (post-LBBD-convergence) -------
        # 2026-06-19: re-lay each tardy bay of the CONVERGED assignment with the
        # windowed CP-SAT packer best-of, obj-gated -> never worse.  Runs on
        # gassign's OWN remaining budget.  KNOWN net-negative in the live ALL40
        # pipeline (it polishes gassign's RAW output, not the box best-of winner,
        # and consuming gassign's tail starves the downstream perbay slot): ALL40
        # @T240 = +4.69% set2.  KEPT as a gated experiment (default OFF) for
        # comparison; the per-bay-slot placement (C, OGC_RELAYOUT) and the
        # subproblem placement (A, OGC_GASSIGN_RELAYOUT_DECODER) are the live
        # candidates.  Gated OGC_GASSIGN_RELAYOUT.
        if sol is not None and _env_on("OGC_GASSIGN_RELAYOUT", False):
            _rl_left = deadline - time.monotonic()
            _rl_min = _env_float("OGC_GASSIGN_RELAYOUT_MIN_S", 12.0)
            if _rl_left >= _rl_min:
                try:
                    import relayout as _rl
                    from utils import check_feasibility as _ckf
                    _sol_r = _rl.polish(prob_info, sol, _rl_left)
                    _cr = _ckf(prob_info, _sol_r)
                    _cc = _ckf(prob_info, sol)
                    if (_cr.get("feasible") and _cc.get("feasible")
                            and _cr.get("objective") is not None
                            and _cc.get("objective") is not None
                            and _cr["objective"] < _cc["objective"] - 1e-9):
                        sol = _sol_r
                except Exception:
                    pass

        return sol
    except Exception:
        return None
