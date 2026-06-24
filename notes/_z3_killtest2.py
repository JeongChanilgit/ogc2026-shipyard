"""z3 global-reassignment KILL-TEST v2 -- entry-TARGETED realization.

v1 (notes/_z3_killtest.py) proved the CP-SAT side works: z1-hard entry domains
+ AddCumulative(alpha * bay area) + pure-z3 objective reached OPTIMAL z3=50 on
prob_4 (current 200) in 18 s.  But realization went through _decode_assignment,
which IGNORES the model's entry times and re-times greedily -> z1=119 blow-up.

v2 fixes the bottleneck: realize the CP-SAT solution the way the dormant
src/myalgorithm.py:_temporal_reassign_redecode_verified does (lines ~3786-3814,
COPIED not called -- its objective is w1-dominated soft-z1) -- pull the model's
entry values as `targets`, order each bay by (target, due) and decode with
_decode_bay(..., release_override=targets) so the packer respects the model's
timing.

Model changes vs the dormant copy:
  * entry[b] domain is z1-HARD: [R, max(R, D-P)].  Blocks with R+P > D keep a
    SOFT tardiness term (those blocks only, warned at startup).
  * objective = w2*z2 + 1000*w3*sum(z3) (+ 1000*w1*T for soft blocks only),
    honouring the 1000x z2 scaling comment at myalgorithm.py:3768-3769.
  * alpha parameterized; workers=2; --topk pref-gap unfix; AddHint kept.

Alpha scan is BIDIRECTIONAL (unlike v1's tighten-only): start at --alpha
(default 0.7); realized z1==0 -> alpha += 0.1 (cap 0.9) chasing lower z3;
z1>0 or realization failure -> alpha -= 0.1 (floor 0.4).  Best z1==0 result
(min z3, verified preferred) is kept across --rounds.

PASS = verified z1 == 0 AND z3 < best-capture z3 * 0.7.

Usage:
  python notes/_z3_killtest2.py --inst prob_4 --alpha 0.7 --topk 100 \
         --cpsat-s 120 --decode-s 300 --rounds 4

NOTE: num_search_workers is hard-coded to 2 so a run can coexist with a
paired validation batch on the same machine.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools"))
import myalgorithm as M
from ortools.sat.python import cp_model

TRAIN = ROOT / "instances" / "train"
CAP = ROOT / "results" / "capture"
COMP_JSON = ROOT / "notes" / "competitor-2026-06-11.json"

CPSAT_WORKERS = 2   # HARD LIMIT: coexist with the running paired batch
ALPHA_MIN, ALPHA_MAX = 0.4, 0.9
SLACK = 0           # entry hi = D - P - SLACK (set from --slack)
RETIME_S = 60.0     # fixed-layout retiming budget after realization (--retime-s)
RMARGIN = 0         # decode may enter up to RMARGIN ticks BEFORE the model
                    # target (release_override = max(R, target - RMARGIN));
                    # the model entry is a witness, not a requirement --
                    # earlier entry can only help realized z1 (--release-margin)
N_ORDERS = 1        # per-bay decode orders tried, best-of by tardiness (--orders)
BANNED = set()      # (block, bay) no-goods accumulated by --ban feedback
REPACK = False      # repack tardy bays via _flatten_decode_one_bay (--repack)


# ---------------------------------------------------------------- best capture
def load_best_capture(inst: str):
    """Best (min met.obj among met.feas) capture for inst across all capture
    dirs -- same scan pattern as notes/_z3_killtest.py."""
    best = None  # (obj, tag, met, solution)
    for d in sorted(CAP.iterdir()):
        if not d.is_dir():
            continue
        f = d / f"{inst}.json"
        if not f.exists():
            continue
        try:
            data = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        met = data.get("met")
        if not met or not met.get("feas") or "solution" not in data:
            continue
        if best is None or met["obj"] < best[0]:
            best = (met["obj"], d.name, met, data["solution"])
    return best


def extract_state(prob: dict, solution: dict):
    """Recover block->bay assignment and entry/exit times from a captured
    solution's operations."""
    id2idx = {blk.get("block_id", i): i for i, blk in enumerate(prob["blocks"])}
    cur_assign, cur_entry, cur_exit = {}, {}, {}
    for t_str, ops in solution["operations"].items():
        t = int(t_str)
        for op in ops:
            b = id2idx[op["block_id"]]
            if op["type"] == "ENTRY":
                cur_assign[b] = op["bay_id"]; cur_entry[b] = t
            else:
                cur_exit[b] = t
    return cur_assign, cur_entry, cur_exit


# -------------------------------------------------------------- block prep
def prep_blocks(prob: dict):
    """Per-block constants (dormant fn lines ~3701-3710) computed ONCE, plus
    the set of blocks where z1=0 is impossible (R+P > D -> soft T term)."""
    blocks = prob["blocks"]
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
        pr = blocks[b]["bay_preferences"]; smax[b] = max(pr); pref[b] = pr
        if R[b] + P[b] > D[b]:
            soft.add(b)
            print(f"    WARNING block {b}: R+P={R[b] + P[b]} > D={D[b]} -- "
                  f"z1=0 impossible, keeping SOFT tardiness term for it")
    return minarea, R, P, D, workload, smax, pref, soft


# ------------------------------------------------------------------ CP-SAT model
def solve_assignment(prob, feasible_bays, cur_assign, cur_entry, free_set,
                     data, bay_u, alpha, cpsat_s):
    """z3+z2-min assignment with z1-HARD entry domains and time-overlap area
    capacity.  Copied from myalgorithm.py:_temporal_reassign_redecode_verified
    (lines ~3717-3782) with: hard entry domains [R, max(R, D-P)] (soft T kept
    only for R+P>D blocks), objective w2*z2 + 1000*w3*z3 (+1000*w1*T_soft),
    alpha/topk/workers=2 parameterization."""
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
        if b not in free_set:
            cj = cur_assign.get(b)
            if cj is not None and (b, cj) in x:
                m.Add(x[b, cj] == 1)        # fixed to current bay
        for j in fb:
            if (b, j) in BANNED and (b, j) in x:
                m.Add(x[b, j] == 0)         # no-good: realization-tardy pair
        if b in soft:
            # z1=0 impossible: wide domain + soft tardiness term (this block only)
            entry[b] = m.NewIntVar(R[b], H, f"e{b}")
            end[b] = m.NewIntVar(R[b] + P[b], H + P[b], f"end{b}")
            m.Add(end[b] == entry[b] + P[b])
            tb = m.NewIntVar(0, H, f"t{b}")
            m.Add(tb >= entry[b] + P[b] - D[b])
            T_soft.append(tb)
        else:
            # z1 HARD: entry >= release AND entry + P <= due - SLACK
            # (SLACK = safety margin absorbing decode-time slippage)
            e_hi = max(R[b], D[b] - P[b] - SLACK)
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
        m.Add(v == sum(terms)); wl.append(v)
    hi = m.NewIntVar(0, wsum * (max(U) + 1), "hi")
    lo = m.NewIntVar(0, wsum * (max(U) + 1), "lo")
    m.AddMaxEquality(hi, wl); m.AddMinEquality(lo, wl)
    z2 = m.NewIntVar(0, wsum * (max(U) + 1), "z2"); m.Add(z2 == hi - lo)

    z3_terms = []
    for (b, j), var in x.items():
        pen = smax[b] - pref[b][j]
        if pen:
            z3_terms.append(pen * var)
    # True objective is w1*Z1 + w2*Z2 + w3*Z3.  z2 here is 1000*Z2 (U=1000*bay_u),
    # so scale all by 1000 to stay integer: 1000*w1*Z1 + w2*z2 + 1000*w3*Z3.
    # Z1 hard-bounded to 0 except for soft (R+P>D) blocks, whose T term remains.
    m.Minimize(1000 * w1 * sum(T_soft) + w2 * z2 + 1000 * w3 * sum(z3_terms))

    # warm start from the captured solution (entry hint clamped into domain)
    for b in range(n_blocks):
        cj = cur_assign.get(b)
        if cj is not None and (b, cj) in x:
            m.AddHint(x[b, cj], 1)
        e_hi = H if b in soft else max(R[b], D[b] - P[b] - SLACK)
        m.AddHint(entry[b], min(max(cur_entry.get(b, R[b]), R[b]), e_hi))

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(cpsat_s)
    s.parameters.num_search_workers = CPSAT_WORKERS
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assign, targets = [0] * n_blocks, {}
    model_z3 = 0
    for b in range(n_blocks):
        for j in (feasible_bays[b] or list(range(n_bays))):
            if (b, j) in x and s.Value(x[b, j]) == 1:
                assign[b] = j
                model_z3 += smax[b] - pref[b][j]
                break
        targets[b] = int(s.Value(entry[b]))
    model_z2 = s.Value(z2) / 1000.0
    return assign, targets, model_z3, model_z2, s.StatusName(st)


# ------------------------------------------------------------------ realization
def realize_and_report(prob, bays_obj, assign, targets, D, bay_u, decode_s):
    """Entry-TARGETED realization (dormant fn lines ~3786-3814, copied): per
    bay, order by (target entry, due) and decode with release_override=targets
    so the packer honours the model timing.  Any bay failing (None/partial)
    fails the round.  Measured with the OFFICIAL metric (v1 verified pattern)."""
    blocks = prob["blocks"]
    n_blocks, n_bays = len(blocks), len(bays_obj)
    by_bay = {j: [] for j in range(n_bays)}
    for b in range(n_blocks):
        by_bay[assign[b]].append(b)
    out_flat, results = [], {}
    dec_dl = time.monotonic() + float(decode_s)
    ro = targets if RMARGIN <= 0 else {
        b: max(int(blocks[b]["release_time"]), targets[b] - RMARGIN)
        for b in range(n_blocks)}
    def _area(b):
        bb = M._block_bbox(blocks[b], 0)
        return (bb[2] - bb[0]) * (bb[3] - bb[1])

    # v4: per-bay multi-order best-of (bays independent given the assignment)
    order_keys = [
        ("tgt,due", lambda b: (targets[b], D[b])),
        ("due,tgt", lambda b: (D[b], targets[b])),
        ("tgt,big", lambda b: (targets[b], -_area(b))),
    ][:max(1, N_ORDERS)]
    for j in range(n_bays):
        ids = by_bay[j]
        if not ids:
            continue
        best_res, best_tard = None, None
        for name, key in order_keys:
            order = sorted(ids, key=key)
            res, _f = M._decode_bay(bays_obj[j], j, order, blocks,
                                    deadline=dec_dl, release_override=ro)
            if res is None or len(res) != len(ids):
                continue
            tard = sum(max(0, int(a["exit_time"]) - int(blocks[b]["due_date"]))
                       for b, a in res.items())
            if best_tard is None or tard < best_tard:
                best_res, best_tard = res, tard
            if tard == 0:
                break
        if best_res is None:
            return None
        results[j] = best_res
        for b in ids:
            out_flat.append(dict(best_res[b]))
    if len(out_flat) != n_blocks:
        return None
    obj, z1, z2, z3 = M._obj_of_results(prob, results, bay_u)
    # v5: repack only the bays still holding tardy blocks (fresh positions via
    # the cross-bay one-bay redecode) -- positional nudge the retimer can't do.
    if z1 > 0 and REPACK:
        hot = sorted({j for j, res in results.items() for b, a in res.items()
                      if int(a["exit_time"]) > int(blocks[b]["due_date"])})
        improved = False
        for j in hot:
            ids = list(results[j])
            old_t = sum(max(0, int(results[j][b]["exit_time"])
                            - int(blocks[b]["due_date"])) for b in ids)
            nr = M._flatten_decode_one_bay(
                prob, bays_obj[j], j, ids, {b: targets[b] for b in ids},
                0.9, 3, time.monotonic() + 30.0)
            if nr is None or len(nr) != len(ids):
                continue
            new_t = sum(max(0, int(nr[b]["exit_time"])
                            - int(blocks[b]["due_date"])) for b in ids)
            if new_t < old_t:
                results[j] = nr
                improved = True
                print(f"    repack bay{j}: bay-tardiness {old_t} -> {new_t}")
        if improved:
            out_flat = [dict(a) for res in results.values()
                        for a in res.values()]
            obj, z1, z2, z3 = M._obj_of_results(prob, results, bay_u)
    # blocks realized past their due (pre-retime superset) -- pin-loop feedback
    tardy = sorted(b for j, res in results.items() for b, a in res.items()
                   if int(a["exit_time"]) > int(blocks[b]["due_date"]))
    # v3: fixed-layout per-bay OPTIMAL crane-feasible retiming (z2/z3 unchanged)
    # to squeeze realization slippage z1 -> its layout minimum.
    if z1 > 0 and RETIME_S > 0:
        cand = M._cpsat_bay_timing_verified(
            prob, bays_obj, results,
            deadline=time.monotonic() + RETIME_S, lb_skip=False)
        if cand is not None:
            c2 = M.check_feasibility(prob, cand)
            if c2["feasible"]:
                print(f"    retime: z1 {z1:.0f} -> {c2['obj1']:.0f} "
                      f"(obj {obj:,.0f} -> {c2['objective']:,.0f})")
                return (c2["objective"], c2["obj1"], c2["obj2"], c2["obj3"],
                        True, tardy)
            print("    retime: candidate failed check_feasibility -- ignored")
    # official 5-stage verdict on the built solution
    chk = M.check_feasibility(prob, {"operations": M._build_operations(out_flat)})
    if chk["feasible"]:
        return (chk["objective"], chk["obj1"], chk["obj2"], chk["obj3"], True,
                tardy)
    print(f"    WARNING: realization produced ops failing check_feasibility "
          f"stage={chk['stage']} -- using internal metric (UNVERIFIED)")
    return obj, z1, z2, z3, False, tardy


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inst", default="prob_4")
    ap.add_argument("--alpha", type=float, default=0.7,
                    help="start cumulative cap = alpha * bay area; bidirectional "
                         "scan: z1=0 -> +0.1 (max 0.9), fail -> -0.1 (min 0.4)")
    ap.add_argument("--topk", type=float, default=100,
                    help="unfix only the top K%% blocks by pref-gap (100 = all)")
    ap.add_argument("--cpsat-s", type=float, default=120,
                    help="CP-SAT time per round (s)")
    ap.add_argument("--decode-s", type=float, default=300,
                    help="decode budget per round (s)")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--slack", type=int, default=0,
                    help="entry hi = D - P - slack (decode slippage margin)")
    ap.add_argument("--retime-s", type=float, default=60.0,
                    help="fixed-layout CP-SAT retiming budget (0 = off)")
    ap.add_argument("--release-margin", type=int, default=0,
                    help="decode may enter up to this many ticks before the "
                         "model target (big value = order-only realization)")
    ap.add_argument("--pin", action="store_true",
                    help="realization-feedback pin loop: keep alpha FIXED; "
                         "after each z1>0 round, pin the realized-tardy blocks "
                         "to their current (working) bay and re-solve. "
                         "Monotone interpolation model-optimal -> current.")
    ap.add_argument("--orders", type=int, default=1,
                    help="per-bay decode orders tried, best-of by tardiness")
    ap.add_argument("--ban", action="store_true",
                    help="realization-feedback no-goods: after each z1>0 "
                         "round, ban the (tardy block, model bay) pairs and "
                         "re-solve at the SAME alpha -- cost is only each "
                         "block's pref-gap to its next-best bay")
    ap.add_argument("--bay-adapt", action="store_true",
                    help="realization-feedback per-bay density: bays holding "
                         "tardy blocks get alpha[j] -= bay-step and the MODEL "
                         "chooses who leaves (globally optimal spill)")
    ap.add_argument("--bay-step", type=float, default=0.05)
    ap.add_argument("--repack", action="store_true",
                    help="repack tardy bays (fresh positions, one-bay "
                         "redecode) before retiming")
    args = ap.parse_args()
    global SLACK, RETIME_S, RMARGIN, N_ORDERS, REPACK
    SLACK = max(0, args.slack)
    RETIME_S = max(0.0, args.retime_s)
    RMARGIN = max(0, args.release_margin)
    N_ORDERS = max(1, args.orders)
    REPACK = bool(args.repack)

    inst = args.inst
    prob = json.load(open(TRAIN / f"{inst}.json", encoding="utf-8"))
    cap = load_best_capture(inst)
    if cap is None:
        print(f"{inst}: no feasible capture found under {CAP}"); sys.exit(1)
    best_obj, best_tag, best_met, best_sol = cap
    comp_obj = json.load(open(COMP_JSON, encoding="utf-8"))[
        "competitor"][inst]["obj"]

    cur_assign, cur_entry, _ = extract_state(prob, best_sol)
    bays_obj = [M.Bay(b["width"], b["height"]) for b in prob["bays"]]
    fb = M._feasible_bays(prob["blocks"], bays_obj)
    bay_areas = [b["width"] * b["height"] for b in prob["bays"]]
    avg_area = sum(bay_areas) / len(bay_areas)
    bay_u = [avg_area / a for a in bay_areas]
    data = prep_blocks(prob)
    D = data[3]

    n_blocks = len(prob["blocks"])
    if args.topk >= 100:
        free_set = set(range(n_blocks))
    else:
        gap = lambda b: (max(prob["blocks"][b]["bay_preferences"])
                         - prob["blocks"][b]["bay_preferences"][cur_assign[b]])
        order = sorted(range(n_blocks), key=gap, reverse=True)
        k = max(1, math.ceil(n_blocks * args.topk / 100.0))
        free_set = set(order[:k])

    best_z3 = best_met.get("z3", float("inf"))
    print(f"=== {inst} === best capture: {best_tag} obj={best_obj:,.0f} "
          f"z1={best_met['z1']:.0f} z3={best_z3:.0f} | competitor obj="
          f"{comp_obj:,.0f} | free={len(free_set)}/{n_blocks} "
          f"workers={CPSAT_WORKERS}")

    alpha = args.alpha
    alpha_vec = [args.alpha] * len(prob["bays"])
    tried = set()
    best_run = None   # (z3, obj, z1, z2, alpha, verified) among z1==0 rounds
    for r in range(1, args.rounds + 1):
        a_key = round(alpha, 2)
        if a_key in tried:
            print(f"[r{r}] alpha={a_key:.2f} already tried -- scan converged, "
                  f"stop")
            break
        tried.add(a_key)
        sol = solve_assignment(prob, fb, cur_assign, cur_entry, free_set,
                               data, bay_u,
                               alpha_vec if args.bay_adapt else alpha,
                               args.cpsat_s)
        if sol is None:
            if args.bay_adapt:
                print(f"[r{r}] alphas={alpha_vec} model INFEASIBLE/timeout "
                      f"-- adaptive floor reached, stop")
                break
            print(f"[r{r}] alpha={alpha:.2f} model INFEASIBLE/timeout "
                  f"(z1-hard + cap too tight) -> alpha-=0.1")
            alpha = max(ALPHA_MIN, alpha - 0.1)
            continue
        assign, targets, model_z3, model_z2, st = sol
        rep = realize_and_report(prob, bays_obj, assign, targets, D, bay_u,
                                 args.decode_s)
        if rep is None:
            print(f"[r{r}] alpha={alpha:.2f} model_z3={model_z3} ({st}) | "
                  f"REALIZATION FAILED (None/partial) -> alpha-=0.1")
            alpha = max(ALPHA_MIN, alpha - 0.1)
            continue
        obj, z1, z2, z3, verified, tardy = rep
        if args.bay_adapt and z1 > 0:
            hot = sorted({assign[b] for b in tardy})
            stepped = [j for j in hot
                       if alpha_vec[j] - args.bay_step >= ALPHA_MIN - 1e-9]
            if stepped:
                for j in stepped:
                    alpha_vec[j] = round(alpha_vec[j] - args.bay_step, 3)
                tried.clear()
                print(f"[r{r}] model_z3={model_z3} ({st}) | realized "
                      f"z1={z1:.0f} z3={z3:.0f} | BAY-ADAPT {stepped} -> "
                      f"alphas={alpha_vec}")
                continue
            print(f"[r{r}] bay-adapt at floor on all hot bays -- stop")
            break
        if args.ban and z1 > 0:
            newban = {(b, assign[b]) for b in tardy} - BANNED
            if newban:
                BANNED.update(newban)
                tried.discard(a_key)   # allow re-solving at the same alpha
                print(f"[r{r}] alpha={alpha:.2f} model_z3={model_z3} ({st}) | "
                      f"realized z1={z1:.0f} z3={z3:.0f} | BAN {len(newban)} "
                      f"(block,bay) pairs -> total {len(BANNED)}")
                continue
            print(f"[r{r}] tardy pairs already banned -- ban loop exhausted")
        if args.pin and z1 > 0:
            newpin = free_set & set(tardy)
            if newpin:
                free_set -= newpin
                tried.discard(a_key)   # allow re-solving at the same alpha
                print(f"[r{r}] alpha={alpha:.2f} model_z3={model_z3} ({st}) | "
                      f"realized z1={z1:.0f} z3={z3:.0f} | PIN {len(newpin)} "
                      f"tardy blocks -> free={len(free_set)}")
                continue
            print(f"[r{r}] tardy blocks already pinned -- pin loop exhausted")
        # assignment realized verbatim => z2/z3 must equal the model's values
        if round(z3) != model_z3:
            print(f"    WARNING: realized z3={z3:.0f} != model z3={model_z3} "
                  f"(assignment drifted?)")
        if abs(z2 - model_z2) > max(1.0, 0.01 * max(z2, model_z2)):
            print(f"    WARNING: realized z2={z2:.1f} != model z2~={model_z2:.1f}")
        tag = ("z1=0, z3x{:.2f} vs best".format(z3 / best_z3)
               if best_z3 > 0 else "z1=0") if z1 == 0 else "z1>0 -> alpha-=0.1"
        if not verified:
            tag += " UNVERIFIED(check_feasibility failed) -> no PASS"
        print(f"[r{r}] alpha={alpha:.2f} model_z3={model_z3} ({st}) | realized "
              f"z1={z1:.0f} z2={z2:.0f} z3={z3:.0f} obj={obj:,.0f} "
              f"verified={verified} | {tag}")
        if z1 == 0:
            cand = (z3, obj, z1, z2, alpha, verified)
            if (best_run is None
                    or (cand[5], ) > (best_run[5], )      # verified beats not
                    or (cand[5] == best_run[5] and cand[0] < best_run[0])):
                best_run = cand
            if args.bay_adapt:
                break                              # adaptive walk is terminal
            alpha = min(ALPHA_MAX, alpha + 0.1)   # chase lower z3
        else:
            alpha = max(ALPHA_MIN, alpha - 0.1)

    if best_run is None:
        print(f"\nBEST: none -- no round realized z1=0")
        verdict = "FAIL"
    else:
        z3, obj, z1, z2, a, verified = best_run
        beats = " | BEATS COMPETITOR" if obj < comp_obj else ""
        print(f"\nBEST: alpha={a:.2f} z1={z1:.0f} z2={z2:.0f} z3={z3:.0f} "
              f"obj={obj:,.0f} verified={verified} | our best obj="
              f"{best_obj:,.0f} | comp obj={comp_obj:,.0f}{beats}")
        verdict = ("PASS" if verified and z3 < best_z3 * 0.7 else "FAIL")

    print(f"{verdict}: " +
          ("realized z1=0 with z3 < 0.7x best -- entry-targeted reassignment "
           "is ALIVE, promote to full track" if verdict == "PASS" else
           "no verified round achieved z1=0 with z3 < 0.7x best -- kill-test "
           "holds, keep z3 global reassignment rejected"))


if __name__ == "__main__":
    main()
