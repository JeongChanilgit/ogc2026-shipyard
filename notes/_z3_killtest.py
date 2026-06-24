"""z3 global-reassignment KILL-TEST probe (time-aware retry of the rejected model).

A competitor reaches z1=0 with z3 ~= 1/4 of ours via preference-first assignment.
The previously rejected CP-SAT assignment model (notes/_z3_pack_test.py) had NO
time dimension, so its z3-optimal assignments exploded z1 when decoded.  This
probe retries with (a) per-bay TIME-OVERLAP area capacity via AddCumulative
(skeleton borrowed from src/myalgorithm.py:_temporal_reassign_redecode_verified,
NOT called -- its objective is w1-dominated) and (b) z1 HARD protection
(entry >= release, entry + P <= due, i.e. tardiness forced to 0 in the model).

Flow per round: CP-SAT (z3-min, z1-hard, alpha*area cumulative cap)
  -> full decode via the real crane-safe packer (_decode_assignment)
  -> official metric (check_feasibility path).  If decoded z1 > 0, tighten
  alpha by 0.1 and re-solve (up to --rounds).

PASS = decoded z1 == 0 AND decoded z3 < best-capture z3 * 0.7.

Usage:
  python notes/_z3_killtest.py --inst prob_4 --alpha 0.6 --topk 100 \
         --cpsat-s 120 --decode-s 300 --rounds 3

NOTE: num_search_workers is hard-coded to 2 so a later run can coexist with a
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


# ---------------------------------------------------------------- best capture
def load_best_capture(inst: str):
    """Best (min met.obj among met.feas) capture for inst across all capture
    dirs -- same scan pattern as notes/_competitor_compare.py."""
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


# ------------------------------------------------------------------ CP-SAT model
def solve_assignment(prob, feasible_bays, cur_assign, cur_entry, free_set,
                     alpha, cpsat_s):
    """z3-min assignment with z1 HARD and time-overlap area capacity.

    Cumulative skeleton borrowed from myalgorithm.py:_temporal_reassign_
    redecode_verified (lines ~3717-3742); objective replaced by pure z3 and
    tardiness replaced by a hard entry+P<=due bound."""
    blocks = prob["blocks"]
    bays = prob["bays"]
    n_blocks, n_bays = len(blocks), len(bays)

    minarea, R, P, D, smax, pref = {}, {}, {}, {}, {}, {}
    for b in range(n_blocks):
        best = math.inf
        for oi in range(len(blocks[b]["shape"])):
            bb = M._block_bbox(blocks[b], oi)
            best = min(best, (bb[2] - bb[0]) * (bb[3] - bb[1]))
        minarea[b] = max(1, int(best))
        R[b] = int(blocks[b]["release_time"])
        P[b] = int(blocks[b]["processing_time"])
        D[b] = int(blocks[b]["due_date"])
        pr = blocks[b]["bay_preferences"]; smax[b] = max(pr); pref[b] = pr
        if R[b] + P[b] > D[b]:
            print(f"    block {b}: R+P={R[b] + P[b]} > D={D[b]} -- z1=0 "
                  f"impossible, model INFEASIBLE by construction")
            return None

    w3 = max(1, int(round(prob.get("weights", {}).get("w3", 1))))

    m = cp_model.CpModel()
    x, entry, end = {}, {}, {}
    for b in range(n_blocks):
        fb = feasible_bays[b] or list(range(n_bays))
        for j in fb:
            x[b, j] = m.NewBoolVar(f"x{b}_{j}")
        m.Add(sum(x[b, j] for j in fb) == 1)
        if b not in free_set:
            cj = cur_assign.get(b)
            if cj is not None and (b, cj) in x:
                m.Add(x[b, cj] == 1)        # fixed to current bay
        # z1 HARD: entry >= release  AND  entry + P <= due
        entry[b] = m.NewIntVar(R[b], D[b] - P[b], f"e{b}")
        end[b] = m.NewIntVar(R[b] + P[b], D[b], f"end{b}")
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
            cap = max(1, int(bays[j]["width"] * bays[j]["height"] * alpha))
            m.AddCumulative(ivs, dems, cap)

    z3_terms = []
    for (b, j), var in x.items():
        pen = smax[b] - pref[b][j]
        if pen:
            z3_terms.append(pen * var)
    m.Minimize(w3 * sum(z3_terms))

    # warm start from the captured solution
    for b in range(n_blocks):
        cj = cur_assign.get(b)
        if cj is not None and (b, cj) in x:
            m.AddHint(x[b, cj], 1)
        e0 = min(max(cur_entry.get(b, R[b]), R[b]), D[b] - P[b])
        m.AddHint(entry[b], e0)

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(cpsat_s)
    s.parameters.num_search_workers = CPSAT_WORKERS
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assign = [0] * n_blocks
    model_z3 = 0
    for b in range(n_blocks):
        for j in (feasible_bays[b] or list(range(n_bays))):
            if (b, j) in x and s.Value(x[b, j]) == 1:
                assign[b] = j
                model_z3 += smax[b] - pref[b][j]
                break
    return assign, model_z3, s.StatusName(st)


# -------------------------------------------------------------------- decode
def decode_report(prob, assign, decode_s):
    """Decode through the real crane-safe packer and measure with the OFFICIAL
    metric -- same pattern as notes/_z3_pack_test.py:60-76, plus a
    check_feasibility pass on the built operations."""
    blocks_data = prob["blocks"]
    bays_obj = [M.Bay(b["width"], b["height"]) for b in prob["bays"]]
    n_bays = len(bays_obj)
    bay_areas = [b["width"] * b["height"] for b in prob["bays"]]
    avg_area = sum(bay_areas) / len(bay_areas)
    bay_u = [avg_area / a for a in bay_areas]
    alt = 40 if len(blocks_data) <= 200 else 0
    dec = M._Decoder(bays_obj, blocks_data, alt)
    deadline = time.monotonic() + float(decode_s)
    results, tard = M._decode_assignment(dec, assign, n_bays, deadline=deadline)
    if results is None:
        return None
    obj, z1, z2, z3 = M._obj_of_results(prob, results, bay_u)
    # official 5-stage verdict on the built solution
    flat = [a for r in results.values() for a in r.values()]
    chk = M.check_feasibility(prob, {"operations": M._build_operations(flat)})
    if chk["feasible"]:
        return chk["objective"], chk["obj1"], chk["obj2"], chk["obj3"], True
    print(f"    WARNING: decode produced ops failing check_feasibility "
          f"stage={chk['stage']} -- using internal metric (UNVERIFIED)")
    return obj, z1, z2, z3, False


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inst", default="prob_4")
    ap.add_argument("--alpha", type=float, default=0.6,
                    help="cumulative cap = alpha * bay area (tightened -0.1/round)")
    ap.add_argument("--topk", type=float, default=100,
                    help="unfix only the top K%% blocks by pref-gap (100 = all)")
    ap.add_argument("--cpsat-s", type=float, default=120,
                    help="CP-SAT time per round (s)")
    ap.add_argument("--decode-s", type=float, default=300,
                    help="decode budget per round (s)")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    inst = args.inst
    prob = json.load(open(TRAIN / f"{inst}.json", encoding="utf-8"))
    cap = load_best_capture(inst)
    if cap is None:
        print(f"{inst}: no feasible capture found under {CAP}"); sys.exit(1)
    best_obj, best_tag, best_met, best_sol = cap
    comp_obj = json.load(open(COMP_JSON, encoding="utf-8"))[
        "competitor"][inst]["obj"]

    cur_assign, cur_entry, _ = extract_state(prob, best_sol)
    fb = M._feasible_bays(prob["blocks"],
                          [M.Bay(b["width"], b["height"]) for b in prob["bays"]])

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
    verdict = "FAIL"
    for r in range(1, args.rounds + 1):
        if alpha <= 0:
            print(f"[r{r}] alpha<=0 -- stop"); break
        sol = solve_assignment(prob, fb, cur_assign, cur_entry, free_set,
                               alpha, args.cpsat_s)
        if sol is None:
            print(f"[r{r}] alpha={alpha:.2f} model INFEASIBLE/timeout "
                  f"(z1-hard + cap too tight) -- stop")
            break
        assign, model_z3, st = sol
        rep = decode_report(prob, assign, args.decode_s)
        if rep is None:
            print(f"[r{r}] alpha={alpha:.2f} model_z3={model_z3} ({st}) | "
                  f"DECODE INFEASIBLE -> alpha-=0.1")
            alpha -= 0.1
            continue
        obj, z1, z2, z3, verified = rep
        tag = ("z1=0, z3x{:.2f} vs best".format(z3 / best_z3)
               if best_z3 > 0 else "z1=0") if z1 == 0 else "z1>0 -> alpha-=0.1"
        if not verified:
            tag += " UNVERIFIED(check_feasibility failed) -> no PASS"
        print(f"[r{r}] alpha={alpha:.2f} model_z3={model_z3} ({st}) | decode "
              f"z1={z1:.0f} z2={z2:.0f} z3={z3:.0f} obj={obj:,.0f} | "
              f"best obj={best_obj:,.0f} | comp obj={comp_obj:,.0f} | {tag}")
        if z1 == 0:
            if verified and z3 < best_z3 * 0.7:
                verdict = "PASS"
            break   # lower alpha cannot improve z3 -- terminal either way
        alpha -= 0.1

    print(f"\n{verdict}: " +
          ("decoded z1=0 with z3 < 0.7x best -- time-aware reassignment is "
           "ALIVE, promote to full track" if verdict == "PASS" else
           "no round achieved z1=0 with z3 < 0.7x best -- kill-test holds, "
           "keep z3 global reassignment rejected"))


if __name__ == "__main__":
    main()
