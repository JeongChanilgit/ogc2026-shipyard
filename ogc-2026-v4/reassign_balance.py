"""
reassign_balance.py -- PROTOTYPE (the OPPOSITE of reassign.py): does LOAD-BALANCING
the bay assignment (move blocks OFF over-full bays onto emptier ones) actually lower
z1 (tardiness) after a crane-safe re-decode, and does it lower the FULL objective?

WHY (Jensen hypothesis):
  Diagnosis showed z1 is CONVEX in a bay's block-count (a bigger bay incurs MORE z1
  per block than a smaller one, e.g. prob_38: ~15 z1/block at n=55->88 vs ~28 z1/block
  at n=88->107).  If z1 is convex in load, then by Jensen's inequality EQUALIZING the
  per-bay block counts (smaller maxload) should LOWER total z1.  We accept some z3
  increase because w1 dominates (z1 ~92% of obj).  This is the inverse of reassign.py,
  which CONCENTRATED blocks into preferred bays (cut z3) and blew up z1.

Pipeline per instance (reassign_balance_decode):
  1. Load current submission real_prob_<i>.json -> base (obj/z1/z2/z3) via global_eval.
  2. CP-SAT LOAD-BALANCE assignment: minimize maxload (the fullest bay's block count),
     with z3 as a tiny secondary tie-breaker, plus a space-time area-capacity guard so
     we don't repeat reassign.py's prob_27 geometry infeasibility.  -> new_assign.
  3. Re-pack each bay's NEW id set crane-safely (build_subset_ids + simulate, edd) -> z1.
  4. (polish=True) crane_repack_bay x/y passes per bay to recover z1, re-eval.
  5. global_eval the result.  NEVER-WORSE gate (report-only): accept iff feasible AND
     new_obj < base_obj.

Reuses reassign._build_subset_ids (per-bay packing `sub` from an arbitrary id list).

Run (env python, 4-worker CP-SAT, from v4 dir):
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe reassign_balance.py 38,27
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe reassign_balance.py        # default 5
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)
_SRC = os.path.join(THIS, "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from ortools.sat.python import cp_model            # noqa: E402
from shapely.geometry import Polygon               # noqa: E402

import adapter                                      # noqa: E402
import seed as _seed                                # noqa: E402
import temporal_pack as _tp                         # noqa: E402
import crane_cpsat                                  # noqa: E402

# REUSE the exact per-bay packing-subset builder from reassign.py.
from reassign import _build_subset_ids              # noqa: E402

_ASSIGN_TL = 15.0      # CP-SAT assignment wall (s)
_PACK_TL = 20.0        # per-bay pack budget hint (s) -- simulate is deterministic/fast
_POLISH_BAY_TL = 20.0  # crane_repack_bay cap per bay (s)
_AREA_SCALE = 100      # float area*proc -> int for CP-SAT
DEFAULT_PROBS = [38, 27, 39, 31, 28]


# ---------------------------------------------------------------------------
def _footprint_area(block: dict, orient_idx: int) -> float:
    """Layer-0 polygon area of `block` in orientation `orient_idx` (fallback 0)."""
    shapes = block["shape"]
    if not (0 <= orient_idx < len(shapes)):
        orient_idx = 0
    layer0 = shapes[orient_idx]["layers"][0]
    return Polygon(layer0).area


# ---------------------------------------------------------------------------
def _solve_loadbalance(data: dict, areas, horizon: int, cur_orient,
                       time_s: float = _ASSIGN_TL):
    """CP-SAT LOAD-BALANCE bay assignment.

    Decision  : x[b][j] in {0,1}, AddExactlyOne(x[b]).
    Loads     : load[j] = sum_b x[b][j]  (block count in bay j).
                maxload >= load[j] for all j.
    Objective : minimize  BIG*maxload + sum_b sum_j x[b][j]*(max_pref[b]-pref[b][j])
                BIG dominates so the FULLEST bay's count is minimized first; the small
                z3 penalty only breaks ties toward keeping preferences.
    Guard     : per-bay space-time area capacity
                sum_b area[b]*proc[b]*x[b][j] <= W_j*H_j*horizon
                (keeps the rebalanced space-time load within bay capacity so we don't
                repeat reassign.py's prob_27 geometry infeasibility).

    Returns (assign{bid:bay}|None, maxload_after|None, status_str).
    """
    blocks = data["blocks"]
    bays = data["bays"]
    nb = len(blocks)
    m = len(bays)
    pref = [list(map(int, blocks[b]["bay_preferences"])) for b in range(nb)]

    # scaled per-block space-time footprint (area*proc), and per-bay capacity.
    area_time = [int(round(areas[b] * blocks[b]["processing_time"] * _AREA_SCALE))
                 for b in range(nb)]
    cap_st = [int(bays[j]["width"] * bays[j]["height"] * horizon * _AREA_SCALE)
              for j in range(m)]

    # z3 magnitude per block -> a BIG so load-balance strictly dominates z3 ties.
    max_z3_block = max((max(pref[b]) - min(pref[b])) for b in range(nb)) if nb else 0
    BIG = 10 * (max_z3_block + 1) * (nb + 1)   # >= nb * max_z3_block (worst total z3)

    model = cp_model.CpModel()
    x = [[model.NewBoolVar(f"x_{b}_{j}") for j in range(m)] for b in range(nb)]
    for b in range(nb):
        model.AddExactlyOne(x[b])

    # space-time capacity guard
    for j in range(m):
        model.Add(sum(area_time[b] * x[b][j] for b in range(nb)) <= cap_st[j])

    # loads + maxload
    loads = []
    for j in range(m):
        lj = model.NewIntVar(0, nb, f"load_{j}")
        model.Add(lj == sum(x[b][j] for b in range(nb)))
        loads.append(lj)
    maxload = model.NewIntVar(0, nb, "maxload")
    for j in range(m):
        model.Add(maxload >= loads[j])

    # objective: BIG*maxload (primary) + raw z3 (secondary tie-break)
    z3_terms = []
    for b in range(nb):
        mx = max(pref[b])
        for j in range(m):
            pen = mx - pref[b][j]
            if pen:
                z3_terms.append(pen * x[b][j])
    model.Minimize(BIG * maxload + sum(z3_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_s
    solver.parameters.num_search_workers = 4
    st = solver.Solve(model)
    name = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE", cp_model.UNKNOWN: "UNKNOWN"}.get(
                st, str(st))
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None, name
    assign = {}
    for b in range(nb):
        for j in range(m):
            if solver.Value(x[b][j]):
                assign[b] = j
                break
    return assign, int(solver.Value(maxload)), name


# ---------------------------------------------------------------------------
def reassign_balance_decode(data: dict, prob_path: str,
                            time_s_pack: float = _PACK_TL,
                            polish: bool = True, scale: int = 2) -> dict:
    """Load-balance reassignment + crane-safe re-decode + honest full-obj eval."""
    prob_idx = int(os.path.basename(prob_path).split("_")[-1].split(".")[0])

    # --- (1) current solution -> base ------------------------------------
    sol = json.load(open(prob_path, encoding="utf-8"))
    cur = adapter.deserialize(data, sol, scale=scale)
    base = _seed.global_eval(data, cur)

    m = len(data["bays"])
    blocks = data["blocks"]

    # current per-bay counts + current orientation (for footprint area) + horizon
    current_counts = [0] * m
    cur_orient = {}
    horizon = 0
    for j, placed in cur.items():
        if 0 <= j < m:
            current_counts[j] += len(placed)
        for pl in placed:
            cur_orient[pl["id"]] = pl.get("orient", 0)
            if pl.get("exit", 0) > horizon:
                horizon = pl["exit"]
    if horizon <= 0:
        horizon = 1
    maxload_before = max(current_counts) if current_counts else 0

    # per-block layer-0 footprint area at its current orientation
    areas = [_footprint_area(blocks[b], cur_orient.get(b, 0)) for b in range(len(blocks))]

    # --- (2) CP-SAT LOAD-BALANCE assignment ------------------------------
    new_assign, maxload_after, st_name = _solve_loadbalance(
        data, areas, horizon, cur_orient, _ASSIGN_TL)
    if new_assign is None:
        return {"prob": prob_idx, "base_obj": base["obj"], "base_z1": base["z1"],
                "base_z2": base["z2"], "base_z3": base["z3"],
                "new_obj": None, "new_z1": None, "new_z3": None,
                "new_feasible": False, "accepted": False,
                "polished_obj": None, "polished_z1": None, "polished_z3": None,
                "maxload_before": maxload_before, "maxload_after": None,
                "status": f"ASSIGN_{st_name}"}

    # --- (3) re-pack each bay's NEW id set crane-safely (fresh) -----------
    by_bay: dict[int, list] = {}
    for bid, j in new_assign.items():
        by_bay.setdefault(j, []).append(bid)

    new_bays_placed: dict[int, list] = {}
    for j, ids in by_bay.items():
        sub = _build_subset_ids(data, j, ids, scale)
        order = _tp.seed_order(sub, "edd")
        placed_j, _z1_j = _tp.simulate(sub, order, allow_stack=False, fit=True)
        new_bays_placed[j] = placed_j

    ev = _seed.global_eval(data, new_bays_placed)

    # --- (4) optional polish: crane_repack_bay x/y passes ----------------
    polished_obj = polished_z1 = polished_z3 = None
    if polish:
        deadline = time.monotonic() + _POLISH_BAY_TL * max(1, len(new_bays_placed))
        polished = {}
        for j, placed_j in new_bays_placed.items():
            rem = deadline - time.monotonic()
            if rem <= 1.0 or not placed_j:
                polished[j] = placed_j
                continue
            try:
                np_j, _stt, _wall, _cinfo = crane_cpsat.crane_repack_bay(
                    data, j, placed_j, min(_POLISH_BAY_TL, rem))
            except Exception:
                np_j = None
            polished[j] = np_j if np_j is not None else placed_j
        pev = _seed.global_eval(data, polished)
        polished_obj, polished_z1, polished_z3 = pev["obj"], pev["z1"], pev["z3"]

    # --- (5) NEVER-WORSE gate (report-only) ------------------------------
    cand_obj = polished_obj if (polish and polished_obj is not None) else ev["obj"]
    cand_feas = (polished_obj is not None) if (polish and polished_obj is not None) \
        else ev["feasible"]
    accepted = bool(cand_feas and cand_obj is not None
                    and base["obj"] is not None and cand_obj < base["obj"])

    return {
        "prob": prob_idx,
        "base_obj": base["obj"], "base_z1": base["z1"],
        "base_z2": base["z2"], "base_z3": base["z3"],
        "new_obj": ev["obj"], "new_z1": ev["z1"], "new_z3": ev["z3"],
        "new_feasible": ev["feasible"],
        "polished_obj": polished_obj, "polished_z1": polished_z1,
        "polished_z3": polished_z3,
        "maxload_before": maxload_before, "maxload_after": maxload_after,
        "accepted": accepted,
        "status": "OK",
    }


# ---------------------------------------------------------------------------
def _fmt(v):
    if v is None:
        return "--"
    return f"{int(round(v)):,}"


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    probs = ([int(x) for x in arg.split(",") if x.strip()] if arg
             else list(DEFAULT_PROBS))
    polish = (os.environ.get("REASSIGN_POLISH", "1") != "0")

    print("=" * 140)
    print("REASSIGN_BALANCE PROTOTYPE -- LOAD-BALANCE the assignment (min maxload, "
          "z3 tie-break, space-time guard), re-decode crane-safely, measure REAL obj.")
    print("  Jensen hypothesis: z1 is CONVEX in bay block-count, so EQUALIZING counts "
          "(smaller maxload) should LOWER total z1.  (OPPOSITE of reassign.py.)")
    print("  NEVER-WORSE gate (report-only): accept iff feasible AND new_obj < base_obj.")
    print("=" * 140)
    hdr = (f"{'prob':>4} | {'base_obj':>13} | {'new(fresh)':>13} | "
           f"{'new(polish)':>13} | {'z1 cur->new':>21} | {'z3 cur->new':>21} | "
           f"{'maxload c->n':>12} | {'acc':>4}")
    print(hdr)
    print("-" * 140)

    rows = []
    for p in probs:
        inst = os.path.normpath(
            os.path.join(THIS, "..", "instances", "train", f"prob_{p}.json"))
        prob_path = os.path.join(THIS, f"real_prob_{p}.json")
        data = json.load(open(inst, encoding="utf-8"))
        t0 = time.monotonic()
        try:
            res = reassign_balance_decode(data, prob_path, _PACK_TL, polish=polish)
        except Exception as e:
            print(f"{p:>4} | ERROR: {type(e).__name__}: {e}", flush=True)
            continue
        res["wall"] = time.monotonic() - t0
        rows.append(res)
        z1s = f"{_fmt(res['base_z1'])} -> {_fmt(res['new_z1'])}"
        z3s = f"{_fmt(res['base_z3'])} -> {_fmt(res['new_z3'])}"
        mls = f"{_fmt(res['maxload_before'])} -> {_fmt(res['maxload_after'])}"
        print(f"{res['prob']:>4} | {_fmt(res['base_obj']):>13} | "
              f"{_fmt(res['new_obj']):>13} | {_fmt(res['polished_obj']):>13} | "
              f"{z1s:>21} | {z3s:>21} | {mls:>12} | "
              f"{'YES' if res['accepted'] else 'no':>4}", flush=True)

    print("-" * 140)
    print("\nVERDICT (did load-balancing REDUCE z1 after re-decode? Jensen check):")
    for res in rows:
        if res["new_obj"] is None or res["base_obj"] is None:
            print(f"  prob_{res['prob']}: {res['status']} "
                  f"(maxload {_fmt(res['maxload_before'])}->{_fmt(res['maxload_after'])})"
                  f"  [{res.get('wall', 0):.1f}s]")
            continue
        dz1 = (res["new_z1"] - res["base_z1"]) if res["new_z1"] is not None else None
        dz3 = (res["new_z3"] - res["base_z3"]) if res["new_z3"] is not None else None
        dml = ((res["maxload_after"] - res["maxload_before"])
               if res["maxload_after"] is not None else None)
        dobj_fresh = res["new_obj"] - res["base_obj"]
        z1_dir = ("z1 DROPPED (Jensen holds)" if (dz1 is not None and dz1 < 0)
                  else "z1 ROSE/flat (Jensen NOT realized)")
        verdict = "NET IMPROVEMENT" if dobj_fresh < 0 else "worse"
        pol = ""
        if res["polished_obj"] is not None:
            dobj_pol = res["polished_obj"] - res["base_obj"]
            pol = (f"  | polish dobj={dobj_pol:+,.0f} "
                   f"({'better' if dobj_pol < 0 else 'still worse'})")
        print(f"  prob_{res['prob']}: maxload {res['maxload_before']}->"
              f"{res['maxload_after']} (d={_fmt(dml)}); z1 d={_fmt(dz1)} ({z1_dir}); "
              f"z3 d={_fmt(dz3)} -> fresh dobj={dobj_fresh:+,.0f} => {verdict}{pol}  "
              f"[{res['wall']:.1f}s]")
    print("=" * 140)


if __name__ == "__main__":
    main()
