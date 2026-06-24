"""Post-hoc CROSS-BAY solution refiner (2026-06-18).

Takes a FULL solution (e.g. gassign's best-of winner) and improves it by moving
blocks ACROSS bays — the one thing perbay (bay-fixed) and box (wholesale) cannot
do.  Bays are SPATIALLY INDEPENDENT, so a move b: bayA->bayB only requires
re-decoding bayA and bayB (not the whole instance).  Every change is gated by the
OFFICIAL checker + strict obj improvement => NEVER worse, never -1.

  Phase A  refine_moves : single-block over-spill moves (cheap, reuses decoder).
  Phase B  refine_alns  : ALNS destroy/repair (subset across bays, greedy re-insert).

Targets the z3 OVER-SPILL deficit (set2 diag: we trail competitor only on z3).
Complementary to the master C3_MULT lever (which PREVENTS over-spill; this FIXES
residual over-spill in the final solution).
"""
from __future__ import annotations
import os, time, math
from utils import Bay, check_feasibility
from baseline_greedy import _build_operations
import fastfloor as ff
import solver_orig as M


def _env_float(n, d):
    try:
        return float(os.environ.get(n, "").strip() or d)
    except Exception:
        return d


# ---------- solution <-> placement ----------
def _parse(sol):
    place = {}
    for ts, ops in sol["operations"].items():
        t = int(ts)
        for op in ops:
            b = op["block_id"]; d = place.setdefault(b, {})
            if op["type"] == "ENTRY":
                d.update(bay=op["bay_id"], x=op["x"], y=op["y"],
                         orient=op["orient_idx"], entry=t)
            else:
                d["exit"] = t
    return place


def _flat(place):
    return [{"block_id": b, "bay_id": p["bay"], "x": p["x"], "y": p["y"],
             "orient_idx": p["orient"], "entry_time": p["entry"],
             "exit_time": p["exit"]} for b, p in place.items()]


def _to_sol(place):
    return {"operations": _build_operations(_flat(place))}


def _obj(prob, place):
    """(feasible, objective) via the OFFICIAL checker."""
    chk = check_feasibility(prob, _to_sol(place))
    if not chk.get("feasible"):
        return False, float("inf")
    return True, chk["objective"]


def _bay_ids(place):
    d = {}
    for b, p in place.items():
        d.setdefault(p["bay"], []).append(b)
    return d


# ---------- re-decode a set of bays (the shared primitive) ----------
def _redecode(prob, place, bays, deadline, b3=True, per_bay_s=5.0):
    """Return a NEW placement with the given bay indices re-decoded (fastfloor BL
    + optional B3 timing oracle), other bays untouched.  None if any bay fails."""
    np_ = {b: dict(p) for b, p in place.items()}
    byb = _bay_ids(np_)
    decoded = {}
    for j in bays:
        ids = byb.get(j, [])
        if not ids:
            continue
        bayo = Bay.from_dict(prob["bays"][j], j)
        dl = min(deadline, time.monotonic() + per_bay_s)
        asgn, _ft = ff._fixed_time_decode(bayo, j, ids, prob["blocks"], dl,
                                          order_key="F0")
        if asgn is None:
            return None
        decoded[j] = asgn
        for b in ids:
            r = asgn[b]
            np_[b].update(x=r["x"], y=r["y"], orient=r["orient_idx"],
                          entry=r["entry_time"], exit=r["exit_time"])
    if b3 and decoded:
        try:
            bays_all = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
            timed = M._cpsat_bay_timing_verified(
                prob, bays_all, decoded, min(deadline, time.monotonic() + 8.0))
            if timed is not None:
                tp = _parse(timed)
                for b, q in tp.items():
                    if b in np_:
                        np_[b].update(x=q["x"], y=q["y"], orient=q["orient"],
                                      entry=q["entry"], exit=q["exit"])
        except Exception:
            pass
    return np_


def _overspilled(prob, place):
    """Blocks NOT on their most-preferred bay, by z3 penalty (s_max - s_chosen) desc."""
    blocks = prob["blocks"]; out = []
    for b, p in place.items():
        prefs = blocks[b]["bay_preferences"]
        s_max = max(prefs)
        pen = s_max - prefs[p["bay"]]
        if pen > 0:
            out.append((pen, b))
    out.sort(reverse=True)
    return [b for _, b in out]


# ---------- Phase A: single-block over-spill cross-bay moves ----------
def refine_moves(prob, sol, time_budget, topk=40, b3=True):
    deadline = time.monotonic() + float(time_budget)   # MONOTONIC (never mix with time.time())
    place = _parse(sol)
    feas, cur = _obj(prob, place)
    if not feas:
        return sol, {"accepted": 0, "tried": 0, "delta": 0.0}
    base = cur
    blocks = prob["blocks"]
    cand = _overspilled(prob, place)[:topk]
    tried = acc = 0
    for b in cand:
        if time.monotonic() >= deadline - 1.0:
            break
        prefs = blocks[b]["bay_preferences"]
        cur_bay = place[b]["bay"]
        # candidate target bays = strictly-better-preference bays (lower z3), best first
        targets = sorted([j for j in range(len(prefs)) if prefs[j] > prefs[cur_bay]],
                         key=lambda j: -prefs[j])
        for j in targets:
            if time.monotonic() >= deadline - 1.0:
                break
            tried += 1
            trial = {bb: dict(p) for bb, p in place.items()}
            trial[b]["bay"] = j
            nd = _redecode(prob, trial, [cur_bay, j], deadline, b3=b3)
            if nd is None:
                continue
            ok, o = _obj(prob, nd)
            if ok and o < cur - 1e-6:
                place = nd; cur = o; acc += 1
                break   # accept this block's move, go to next block
    return _to_sol(place), {"accepted": acc, "tried": tried, "delta": cur - base,
                            "base": base, "final": cur}


# ---------- Phase B: ALNS destroy/repair across bays ----------
def refine_alns(prob, sol, time_budget, subset=6, b3=True, seed=1, sa=False, T0=None):
    import random
    deadline = time.monotonic() + float(time_budget)   # MONOTONIC (never mix with time.time())
    rng = random.Random(seed)
    place = _parse(sol)
    feas, cur = _obj(prob, place)
    if not feas:
        return sol, {"iters": 0, "acc": 0, "delta": 0.0}
    base = cur
    best = {b: dict(p) for b, p in place.items()}; best_obj = cur
    blocks = prob["blocks"]
    nbays = len(prob["bays"])
    t_start = time.monotonic()
    iters = acc = 0

    def pick_subset():
        op = rng.random()
        if op < 0.5:                       # over-spilled (z3)
            pool = _overspilled(prob, place)
        elif op < 0.8:                     # tardy (z1)
            pool = sorted([b for b in place
                           if place[b]["exit"] > blocks[b]["due_date"]],
                          key=lambda b: place[b]["exit"] - blocks[b]["due_date"],
                          reverse=True)
        else:                              # random
            pool = list(place.keys()); rng.shuffle(pool)
        return pool[:subset]

    while time.monotonic() < deadline - 2.0:
        S = pick_subset()
        if not S:
            break
        iters += 1
        # affected bays = current bays of S
        src_bays = set(place[b]["bay"] for b in S)
        trial = {b: dict(p) for b, p in place.items()}
        # REPAIR: greedily re-insert each freed block to its best feasible bay
        # (preferred first), re-decoding affected bays; cross-bay.
        touched = set(src_bays)
        for b in S:
            prefs = blocks[b]["bay_preferences"]
            order = sorted(range(nbays), key=lambda j: -prefs[j])
            # tentatively move to most-preferred (cross-bay); decode decides feasibility
            best_j = trial[b]["bay"]
            for j in order[:3]:            # try top-3 preferred bays
                if j == trial[b]["bay"]:
                    continue
                trial[b]["bay"] = j; touched.add(j)
                break
        nd = _redecode(prob, trial, list(touched), deadline, b3=b3)
        if nd is None:
            continue
        ok, o = _obj(prob, nd)
        accept = ok and o < cur - 1e-6
        if not accept and sa and ok:
            T = max(1.0, (T0 or base * 0.002) *
                    max(0.0, (deadline - time.monotonic()) / max(1e-9, deadline - t_start)))
            try:
                accept = rng.random() < math.exp(-(o - cur) / T)
            except OverflowError:
                accept = False
        if accept:
            place = nd; cur = o; acc += 1
            if cur < best_obj:
                best_obj = cur; best = {b: dict(p) for b, p in place.items()}
    return _to_sol(best), {"iters": iters, "acc": acc, "delta": best_obj - base,
                           "base": base, "final": best_obj}
