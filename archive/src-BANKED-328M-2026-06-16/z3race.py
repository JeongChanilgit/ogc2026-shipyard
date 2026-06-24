"""z3 global-reassignment race candidate -- pipeline-stage port of the verified
probe notes/_z3_killtest2.py (prob_16: verified z1=0, obj 75,425 vs best-ever
96,187 = -21.6%; winning recipe = --ban --orders 3 --repack --retime-s 60
@ alpha 0.7).

Single public entry: z3_race_candidate().  Starting from the CURRENT verified
solution (the caller's per-bay `results`), it re-solves the block->bay
assignment with a z1-HARD CP-SAT model (entry domains [R, max(R, D-P)],
AddCumulative(alpha * bay area), objective w2*z2 + 1000*w3*z3 plus a soft
tardiness term only for R+P>D blocks), realizes the model ENTRY-TARGETED
(per-bay best-of-n_orders decode with release_override=targets), repairs
residual z1 (hot-bay repack via _flatten_decode_one_bay, then fixed-layout
optimal retiming via _cpsat_bay_timing_verified) and, when a round still ends
z1>0, feeds the realization-tardy (block, model-bay) pairs back as no-goods
and re-solves (the probe's --ban loop, up to max_feedback rounds).

Returns the first z1=0 check_feasibility-verified candidate, or None.
ADOPTION IS THE CALLER'S JOB (consider-style objective gate) -- this module
never touches the incumbent.  Every step is deadline-guarded and the whole
body is exception-safe (any failure -> None), so a losing or crashing race
costs only its budgeted time.

Differences vs the probe (intentional):
  * state comes from the caller's per-bay `results`, not a capture file;
  * alpha is FIXED (no bidirectional scan) -- ban feedback is the only loop,
    and the run stops at the first verified z1=0 candidate (same alpha + same
    ban set would only re-solve the identical model);
  * silent (no prints); workers/cpsat_s parameterized (probe hard-coded 2
    workers to coexist with a batch); repack budget ~8 s/bay (probe: 30) and
    retime ~20 s (probe: --retime-s 60) to fit a ~120 s pipeline slice;
  * myalgorithm is imported LAZILY inside the entry (a module-level
    `from myalgorithm import ...` would be an import cycle once myalgorithm
    itself imports z3race).

INTEGRATION (apply only AFTER the running full-20 validation batch finishes --
src/myalgorithm.py must not change while it runs).  Place in algorithm()'s pp
race region, right after the T1 race block (the `except ... tr.log(
"race_error")` end, ~line 5540, just before the OGC_EXIT_ON_Z1_ZERO check).
NOTE: consider() is scoped inside _postprocess_verified_solution and is NOT
visible there, so the snippet uses the same objective-gated floor-promotion
idiom as race_floor (myalgorithm.py:5522) -- functionally the
consider("z3_race") gate:

    # ---- z3 global-reassignment race (z3race.py, default OFF).  Arms only
    # at long tl on a z1=0 floor with a full slice of budget left; adoption
    # stays behind the strict-< objective gate, so a losing race costs only
    # OGC_Z3RACE_S seconds.
    if (_env_on("OGC_Z3_RACE", False)
            and T >= _env_float("OGC_Z3RACE_MIN_T", 300.0)
            and time.monotonic() + _env_float("OGC_Z3RACE_S", 120.0) + 10.0
            <= pp_deadline):
        try:
            _zc = _components_from_solution(prob_info, floor_sol, bay_u)
            if _zc is not None and float(_zc[1]) <= 1e-9:  # best_z1 == 0
                import z3race as _z3r  # lazy: src/ already on sys.path
                _zres = _results_from_solution(prob_info, floor_sol)[1]
                _zsol = _z3r.z3_race_candidate(
                    prob_info, bays, feasible_bays, _zres, bay_u,
                    deadline=time.monotonic()
                    + _env_float("OGC_Z3RACE_S", 120.0))
                _zobj = None
                if _zsol is not None:
                    _zrep = check_feasibility(prob_info, _zsol)
                    if (_zrep.get("feasible")
                            and _zrep.get("objective") is not None):
                        _zobj = _zrep["objective"]
                        if _zobj < floor_obj - 1e-9:  # consider("z3_race")
                            floor_obj, floor_label, floor_sol = \
                                _zobj, "z3_race", _zsol
                if tr.enabled:
                    tr.log("z3_race", obj=_zobj,
                           adopted=(floor_label == "z3_race"))
        except Exception:
            pass
"""
import math
import os
import sys
import time

_DBG = os.environ.get("OGC_Z3RACE_DEBUG", "") == "1"


def _dbg(msg):
    if _DBG:
        print(f"[Z3RACE] {msg}", file=sys.stderr, flush=True)


_MARGIN = 10.0          # stop the feedback loop when less than this remains (s)
_DECODE_RESERVE = 5.0   # headroom kept off the deadline for decode/check (s)
_REPACK_MIN_S = 4.0     # per-bay repack CP-SAT floor (myalgorithm's hard cap)
_REPACK_MAX_S = float(os.environ.get("OGC_Z3RACE_REPACK_MAX_S", "30"))  # per-bay repack CP-SAT ceiling (probe used 30 s)
_REPACK_DECODE_S = 4.0  # decode headroom granted on top of the CP-SAT budget
_RETIME_S = float(os.environ.get("OGC_Z3RACE_RETIME_S", "20"))  # fixed-layout retiming budget (probe: --retime-s 60)


def z3_race_candidate(prob_info, bays, feasible_bays, results, bay_u,
                      deadline, alpha=0.7, n_orders=3, max_feedback=6,
                      cpsat_s=45.0, workers=4):
    """results(현재 verified 솔루션의 per-bay dict)에서 출발해 z3-최적 재배정
    후보를 만든다. 반환: {"operations": ...} 솔루션 dict (z1=0 실현 성공 시) 또는
    None. 채택 판정은 호출자(consider 게이트)가 한다.

    deadline: time.monotonic() 기준 절대 시각 (모든 단계가 이를 엄수).
    alpha: 스칼라 또는 베이별 list/dict (AddCumulative cap = alpha_j * 면적).
    n_orders: 베이당 실현 디코드 오더 수, 1..5 (4-5번째는 해시-셔플 변형).
    """
    try:
        return _race(prob_info, bays, feasible_bays, results, bay_u,
                     float(deadline), alpha, min(5, max(1, int(n_orders))),
                     max(0, int(max_feedback)), float(cpsat_s), int(workers))
    except Exception:
        return None


def _race(prob_info, bays, feasible_bays, results, bay_u, deadline,
          alpha, n_orders, max_feedback, cpsat_s, workers):
    import myalgorithm as M                      # lazy: avoids import cycle
    from ortools.sat.python import cp_model

    blocks = prob_info["blocks"]
    n_blocks = len(blocks)

    # 1. current assignment / entry times from the caller's verified results.
    cur_assign, cur_entry = {}, {}
    for j, res in results.items():
        for b, a in res.items():
            cur_assign[b] = j
            cur_entry[b] = int(a["entry_time"])
    if len(cur_assign) != n_blocks:
        return None

    data = _prep_blocks(M, blocks)
    D = data[3]
    banned = set()        # (block, bay) no-goods from realization feedback
    best = None           # (obj, solution) among z1=0 verified candidates
    pending = None        # (assign, targets) reused by realize-only retries
    retry_r = 0           # >0 -> shuffled-order retry round (ban was useless)

    last_cost = 0.0       # measured wall of the previous round
    for _r in range(max_feedback + 1):
        rem = deadline - time.monotonic()
        # don't start a round we can't afford: a deadline-starved decode
        # force-places its tail (measured: z1 6994) -- pure waste.
        if rem < max(_MARGIN, 0.8 * last_cost):
            _dbg(f"r{_r} skipped: rem={rem:.0f}s < round cost ~{last_cost:.0f}s")
            break
        _t_round = time.monotonic()
        # 2. z1-hard CP-SAT reassignment, clamped to the remaining window
        # (skipped on retry rounds: same model solution, realization only).
        if pending is None:
            sol = _solve_assignment(cp_model, prob_info, feasible_bays,
                                    cur_assign, cur_entry, data, bay_u, alpha,
                                    min(cpsat_s, rem - _MARGIN), workers,
                                    banned)
            if sol is None:
                _dbg(f"r{_r} model infeasible/timeout (bans={len(banned)})")
                break     # model infeasible/timeout under this ban set
            assign, targets = sol
            if _DBG:
                smax, pref = data[5], data[6]
                _dbg(f"r{_r} model z3="
                     f"{sum(smax[b] - pref[b][assign[b]] for b in assign)} "
                     f"(bans={len(banned)}, rem={rem:.0f}s)")
        else:
            assign, targets = pending
            pending = None
            _dbg(f"r{_r} retry round {retry_r} (shuffled orders)")
        # 3. entry-targeted realization (per-bay best-of-n_orders decode;
        # retry rounds widen to 5 orders incl. the hash-shuffled variants).
        rres = _realize(M, prob_info, bays, assign, targets, D,
                        5 if retry_r else n_orders,
                        deadline - _DECODE_RESERVE,
                        shuffle_r=retry_r if retry_r else None)
        if rres is None:
            _dbg(f"r{_r} realization FAILED (bay None/partial)")
            break         # a bay failed (None/partial) -> round fails
        obj, z1, z2, z3 = M._obj_of_results(prob_info, rres, bay_u)
        _dbg(f"r{_r} realized z1={z1:.0f} z3={z3:.0f} obj={obj:.0f}")
        # 4a. hot-bay repack: fresh positions the retimer can't produce.
        if z1 > 0 and deadline - time.monotonic() > _MARGIN:
            if _repack_hot_bays(M, prob_info, bays, rres, targets,
                                deadline - _DECODE_RESERVE):
                obj, z1, z2, z3 = M._obj_of_results(prob_info, rres, bay_u)
                _dbg(f"r{_r} repacked  z1={z1:.0f} obj={obj:.0f}")
        # realized-tardy blocks (post-repack, pre-retime) -- ban feedback keys
        tardy = sorted(b for res in rres.values() for b, a in res.items()
                       if int(a["exit_time"]) > int(blocks[b]["due_date"]))
        cand = None
        if z1 <= 1e-9:
            flat = [dict(a) for res in rres.values() for a in res.values()]
            chk_sol = {"operations": M._build_operations(flat)}
            chk = M.check_feasibility(prob_info, chk_sol)
            if chk.get("feasible") and (chk.get("obj1") or 0.0) <= 1e-9:
                cand = (chk["objective"], chk_sol)
        elif z1 <= 3 and deadline - time.monotonic() > _MARGIN:
            # 4b. fixed-layout OPTIMAL crane-feasible retiming (z2/z3 fixed):
            # squeeze realization slippage z1 down to its layout minimum.
            # Only near convergence (z1<=3): at higher z1 the layout itself is
            # wrong and the ~20 s is better spent on another ban round.
            rt = M._cpsat_bay_timing_verified(
                prob_info, bays, rres,
                deadline=min(deadline - _DECODE_RESERVE,
                             time.monotonic() + _RETIME_S),
                lb_skip=False)
            if rt is not None:
                chk = M.check_feasibility(prob_info, rt)
                _dbg(f"r{_r} retimed  feas={chk.get('feasible')} "
                     f"z1={chk.get('obj1')} obj={chk.get('objective')}")
                if chk.get("feasible") and (chk.get("obj1") or 0.0) <= 1e-9:
                    cand = (chk["objective"], rt)
            else:
                _dbg(f"r{_r} retime returned None")
        if cand is not None:
            if best is None or cand[0] < best[0]:
                best = cand
            break         # fixed alpha + same bans -> re-solve adds nothing
        # 5. ban feedback: forbid the realized-tardy (block, MODEL bay) pairs
        # and re-solve -- cost is only each block's pref-gap to its next bay.
        # When ban is USELESS (no new pairs, or <3 bays so the only "next bay"
        # explodes z3 -- prob_4 measured 0 -> 662), fall back to a realize-only
        # RETRY round: same model solution, shuffled decode orders + the
        # budget-scaled repack get another shot (seed differs every round).
        newban = {(b, assign[b]) for b in tardy} - banned
        if newban and len(bays) >= 3:
            banned |= newban
            retry_r = 0
        else:
            retry_r += 1
            pending = (assign, targets)
        last_cost = time.monotonic() - _t_round

    return best[1] if best is not None else None


def _prep_blocks(M, blocks):
    """Per-block constants (probe prep_blocks, silent): min-orientation bbox
    area, R/P/D, workload, smax/pref, plus the soft set (R+P > D -> z1=0
    impossible, those blocks keep a soft tardiness term in the model)."""
    minarea, R, P, D, workload, smax, pref = {}, {}, {}, {}, {}, {}, {}
    soft = set()
    for b in range(len(blocks)):
        best = math.inf
        for oi in range(len(blocks[b]["shape"])):
            bb = M._block_bbox(blocks[b], oi)
            best = min(best, (bb[2] - bb[0]) * (bb[3] - bb[1]))
        minarea[b] = max(1, int(best))
        R[b] = int(blocks[b]["release_time"])
        P[b] = int(blocks[b]["processing_time"])
        D[b] = int(blocks[b]["due_date"])
        workload[b] = int(round(blocks[b]["workload"]))
        pr = blocks[b]["bay_preferences"]
        smax[b] = max(pr)
        pref[b] = pr
        if R[b] + P[b] > D[b]:
            soft.add(b)
    return minarea, R, P, D, workload, smax, pref, soft


def _solve_assignment(cp_model, prob, feasible_bays, cur_assign, cur_entry,
                      data, bay_u, alpha, cpsat_s, workers, banned):
    """z3+z2-min reassignment with z1-HARD entry domains and time-overlap area
    capacity (probe solve_assignment): per bay AddCumulative(alpha_j * area),
    objective w2*z2 + 1000*w3*Z3 (+ 1000*w1*T for soft R+P>D blocks only --
    z2 carries the 1000x U scaling so everything stays integer), warm-started
    from the current state; `banned` (block, bay) pairs are excluded.
    Returns (assign, targets) or None."""
    if cpsat_s < 1.0:
        return None
    blocks = prob["blocks"]
    bays = prob["bays"]
    n_blocks, n_bays = len(blocks), len(bays)
    minarea, R, P, D, workload, smax, pref, soft = data

    w = prob.get("weights", {})
    w1 = max(1, int(round(w.get("w1", 1))))
    w2 = max(1, int(round(w.get("w2", 1))))
    w3 = max(1, int(round(w.get("w3", 1))))

    m = cp_model.CpModel()
    H = max(D.values()) + sum(P.values())
    x, entry, end = {}, {}, {}
    T_soft = []
    for b in range(n_blocks):
        fb = feasible_bays[b] or list(range(n_bays))
        for j in fb:
            x[b, j] = m.NewBoolVar(f"x{b}_{j}")
        m.Add(sum(x[b, j] for j in fb) == 1)
        for j in fb:
            if (b, j) in banned:
                m.Add(x[b, j] == 0)     # no-good: realization-tardy pair
        if b in soft:
            # z1=0 impossible: wide domain + soft tardiness (this block only)
            entry[b] = m.NewIntVar(R[b], H, f"e{b}")
            end[b] = m.NewIntVar(R[b] + P[b], H + P[b], f"end{b}")
            m.Add(end[b] == entry[b] + P[b])
            tb = m.NewIntVar(0, H, f"t{b}")
            m.Add(tb >= entry[b] + P[b] - D[b])
            T_soft.append(tb)
        else:
            # z1 HARD: entry >= release AND entry + P <= due
            e_hi = max(R[b], D[b] - P[b])
            entry[b] = m.NewIntVar(R[b], e_hi, f"e{b}")
            end[b] = m.NewIntVar(R[b] + P[b], e_hi + P[b], f"end{b}")
            m.Add(end[b] == entry[b] + P[b])

    bay_blocks = {j: [] for j in range(n_bays)}
    for (b, j) in x:
        bay_blocks[j].append(b)
    for j in range(n_bays):
        ivs, dems = [], []
        for b in bay_blocks[j]:
            ivs.append(m.NewOptionalIntervalVar(entry[b], P[b], end[b],
                                                x[b, j], f"iv{b}_{j}"))
            dems.append(minarea[b])
        if ivs:
            aj = alpha[j] if isinstance(alpha, (list, dict)) else alpha
            cap = max(1, int(bays[j]["width"] * bays[j]["height"] * aj))
            m.AddCumulative(ivs, dems, cap)

    U = [int(round(bay_u[j] * 1000)) for j in range(n_bays)]
    wsum = sum(workload.values()) + 1
    wl = []
    for j in range(n_bays):
        terms = [workload[b] * U[j] * x[b, j] for b in bay_blocks[j]]
        v = m.NewIntVar(0, wsum * (max(U) + 1), f"wl{j}")
        m.Add(v == sum(terms))
        wl.append(v)
    hi = m.NewIntVar(0, wsum * (max(U) + 1), "hi")
    lo = m.NewIntVar(0, wsum * (max(U) + 1), "lo")
    m.AddMaxEquality(hi, wl)
    m.AddMinEquality(lo, wl)
    z2 = m.NewIntVar(0, wsum * (max(U) + 1), "z2")
    m.Add(z2 == hi - lo)

    z3_terms = []
    for (b, j), var in x.items():
        pen = smax[b] - pref[b][j]
        if pen:
            z3_terms.append(pen * var)
    # True objective is w1*Z1 + w2*Z2 + w3*Z3.  z2 here is 1000*Z2, so scale
    # all by 1000: 1000*w1*Z1_soft + w2*z2 + 1000*w3*Z3 (Z1 hard-bounded to 0
    # except for the soft R+P>D blocks).
    m.Minimize(1000 * w1 * sum(T_soft) + w2 * z2 + 1000 * w3 * sum(z3_terms))

    # warm start from the current verified state (entry clamped into domain)
    for b in range(n_blocks):
        cj = cur_assign.get(b)
        if cj is not None and (b, cj) in x:
            m.AddHint(x[b, cj], 1)
        e_hi = H if b in soft else max(R[b], D[b] - P[b])
        m.AddHint(entry[b], min(max(cur_entry.get(b, R[b]), R[b]), e_hi))

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(cpsat_s)
    s.parameters.num_search_workers = max(1, int(workers))
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assign, targets = [0] * n_blocks, {}
    for b in range(n_blocks):
        for j in (feasible_bays[b] or list(range(n_bays))):
            if (b, j) in x and s.Value(x[b, j]) == 1:
                assign[b] = j
                break
        targets[b] = int(s.Value(entry[b]))
    return assign, targets


def _realize(M, prob, bays, assign, targets, D, n_orders, dec_dl,
             shuffle_r=None):
    """Entry-TARGETED realization (probe realize_and_report, decode part):
    per bay try up to n_orders (<=5) block orders, decode with
    release_override=targets so the packer honours the model timing, keep the
    lowest-tardiness complete result.  Any bay failing (None/partial) fails
    the whole round -> None.  Orders 4-5 are hash-shuffled variants seeded by
    shuffle_r (int-tuple hash = deterministic, no random module), so retry
    rounds break the determinism of the base 3 keys -- a different shuffle
    every round instead of replaying the exact blocked packing."""
    blocks = prob["blocks"]
    n_bays = len(bays)
    by_bay = {j: [] for j in range(n_bays)}
    for b, j in enumerate(assign):
        by_bay[j].append(b)

    def _area(b):
        bb = M._block_bbox(blocks[b], 0)
        return (bb[2] - bb[0]) * (bb[3] - bb[1])

    r = 0 if shuffle_r is None else int(shuffle_r)
    order_keys = [
        lambda b: (targets[b], D[b]),
        lambda b: (D[b], targets[b]),
        lambda b: (targets[b], -_area(b)),
        # deterministic shuffles: a coarse leading hash bucket (strong
        # perturbation) and a hashed tie-breaker after target (mild).
        lambda b: (hash((b, r)) % 17, targets[b], D[b]),
        lambda b: (targets[b], hash((b, r, 1)) % 251, D[b]),
    ][:max(1, min(5, n_orders))]
    out = {}
    for j in range(n_bays):
        ids = by_bay[j]
        if not ids:
            continue
        best_res, best_tard = None, None
        for key in order_keys:
            order = sorted(ids, key=key)
            res, _f = M._decode_bay(bays[j], j, order, blocks,
                                    deadline=dec_dl,
                                    release_override=targets)
            if res is None or len(res) != len(ids):
                continue
            tard = sum(max(0, int(a["exit_time"])
                           - int(blocks[b]["due_date"]))
                       for b, a in res.items())
            if best_tard is None or tard < best_tard:
                best_res, best_tard = res, tard
            if tard == 0:
                break
        if best_res is None:
            return None
        out[j] = best_res
    if sum(len(r) for r in out.values()) != len(blocks):
        return None
    return out


def _repack_hot_bays(M, prob, bays, rres, targets, deadline):
    """Repack only the bays still holding tardy blocks (fresh positions via
    the budget-scaled one-bay redecode below) -- a positional nudge the
    fixed-layout retimer can't do.  The per-bay CP-SAT budget splits the
    remaining window across the hot bays (clamped to
    [_REPACK_MIN_S, _REPACK_MAX_S]); myalgorithm's own helper hard-caps the
    solve at 4 s, far too short for the 100-300-block bay timing models this
    race repacks.  Mutates rres in place; returns True if any bay's tardiness
    improved (probe realize_and_report, --repack part)."""
    blocks = prob["blocks"]
    hot = sorted({j for j, res in rres.items() for b, a in res.items()
                  if int(a["exit_time"]) > int(blocks[b]["due_date"])})
    if not hot:
        return False
    budget = max(_REPACK_MIN_S,
                 min(_REPACK_MAX_S,
                     (deadline - time.monotonic() - _MARGIN) / len(hot)))
    improved = False
    for j in hot:
        if deadline - time.monotonic() < 2.0:
            break
        ids = list(rres[j])
        old_t = sum(max(0, int(rres[j][b]["exit_time"])
                        - int(blocks[b]["due_date"])) for b in ids)
        nr = _flatten_one_bay(
            M, prob, bays[j], j, ids, {b: targets[b] for b in ids},
            0.9, 3,
            min(deadline, time.monotonic() + budget + _REPACK_DECODE_S),
            cpsat_budget=budget)
        if nr is None or len(nr) != len(ids):
            continue
        new_t = sum(max(0, int(nr[b]["exit_time"])
                        - int(blocks[b]["due_date"])) for b in ids)
        if new_t < old_t:
            rres[j] = nr
            improved = True
    return improved


def _flatten_one_bay(M, prob_info, bay, bay_idx, ids, warm_entries, alpha,
                     n_orders, deadline, cpsat_budget):
    """Budget-scaled copy of myalgorithm._flatten_decode_one_bay (:3031):
    identical demand-flattened best-of re-decode of a bay's block set `ids`,
    except the inner CP-SAT time limit is an argument instead of the 4 s hard
    cap (deadline-clamped, skipped entirely when <1 s remains).  Returns the
    lowest-tardiness res dict {block_id: assignment} or None."""
    blocks = prob_info["blocks"]
    if not ids:
        return {}
    targets = {b: int(blocks[b]["release_time"]) for b in ids}
    try:
        from ortools.sat.python import cp_model
        cp_s = float(cpsat_budget)
        if deadline is not None:
            cp_s = min(cp_s, deadline - time.monotonic() - 1.0)
        if cp_s >= 1.0:
            cap = max(1, int(bay.width * bay.height * alpha))
            m = cp_model.CpModel()
            H = (max(int(blocks[b]["due_date"]) for b in ids)
                 + sum(int(blocks[b]["processing_time"]) for b in ids))
            e = {}; ivs = []; dem = []; tard = []
            for b in ids:
                blk = blocks[b]
                ar = max(1, int(min(
                    (M._block_bbox(blk, oi)[2] - M._block_bbox(blk, oi)[0])
                    * (M._block_bbox(blk, oi)[3] - M._block_bbox(blk, oi)[1])
                    for oi in range(len(blk["shape"])))))
                R = int(blk["release_time"]); P = int(blk["processing_time"])
                D = int(blk["due_date"])
                ev = m.NewIntVar(R, H, f"e{b}"); e[b] = ev
                xv = m.NewIntVar(R, H + P, f"x{b}")
                ivs.append(m.NewIntervalVar(ev, P, xv, f"i{b}"))
                dem.append(min(ar, cap))
                tv = m.NewIntVar(0, H, f"t{b}"); m.Add(tv >= ev + P - D)
                tard.append(tv)
                m.AddHint(ev, int(warm_entries.get(b, R)))
            m.AddCumulative(ivs, dem, cap); m.Minimize(sum(tard))
            s = cp_model.CpSolver()
            s.parameters.max_time_in_seconds = cp_s
            s.parameters.num_search_workers = 2
            M._dev_det(s)
            st = (s.Solve(m, M._zero_obj_stopper(cp_model))
                  if M._CPSAT_ZERO_STOP else s.Solve(m))
            if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                targets = {b: int(s.Value(e[b])) for b in ids}
    except Exception:
        pass
    best_res = None; best_bt = math.inf
    okeys = [
        lambda b: (targets[b], blocks[b]["due_date"]),
        lambda b: (blocks[b]["due_date"], targets[b]),
        lambda b: (targets[b], blocks[b]["due_date"]
                   - blocks[b]["release_time"] - blocks[b]["processing_time"]),
    ][:max(1, n_orders)]
    for k in okeys:
        if deadline is not None and time.monotonic() >= deadline - 0.3:
            break
        order = sorted(ids, key=k)
        res, _f = M._decode_bay(bay, bay_idx, order, blocks, deadline=deadline,
                                release_override=targets,
                                fast_geom=M._REDECODE_FAST or None)
        if res is None or len(res) != len(ids):
            continue
        bt = sum(max(0, res[b]["exit_time"] - blocks[b]["due_date"])
                 for b in ids)
        if bt < best_bt:
            best_bt = bt; best_res = res
    return best_res
