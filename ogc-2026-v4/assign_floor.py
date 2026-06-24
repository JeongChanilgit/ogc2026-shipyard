"""
assign_floor.py -- CP-SAT LOWER BOUND on z3 (preference deviation) achievable by
pure bay REASSIGNMENT under capacity constraints.

DIAGNOSTIC ONLY.  This quantifies how much z3 we could *optimistically* recover by
moving blocks to more-preferred bays, ignoring the (NP-hard) spatial-packing and
crane feasibility that the real solver must respect.  The capacity here is an
APPROXIMATION, so:

  * SPACE-TIME floor  -> very optimistic (assumes perfect space-time packing).
    The resulting z3_floor is a true LOWER BOUND on z3, so the gap is an
    UPPER BOUND on recoverable z3.  Small gap => definitely can't cut much.
    Large gap => MIGHT be recoverable (not guaranteed -- packing may forbid it).
  * COUNT+15% floor   -> realistic.  Cap each bay at ceil(1.15 * current_count[j])
    blocks (allow 15% more than currently placed).  This is our honest estimate.

For each set2 instance we compare z3_cur (from the real submission solution) with
both z3_floor values and report the gaps + the w3-weighted obj reduction potential.

Run:
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe assign_floor.py
"""
from __future__ import annotations

import json
import math
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

from shapely.geometry import Polygon          # noqa: E402
from ortools.sat.python import cp_model       # noqa: E402
import utils as _utils                         # noqa: E402

# scale for converting float area*time products to CP-SAT ints
_AREA_SCALE = 100          # area is float -> *100 then round
_SOLVE_TL = 15.0           # seconds per instance


# ---------------------------------------------------------------------------
def _footprint_area(block: dict, orient_idx: int) -> float:
    """Layer-0 polygon area of `block` in orientation `orient_idx` (fallback 0)."""
    shapes = block["shape"]
    if not (0 <= orient_idx < len(shapes)):
        orient_idx = 0
    layer0 = shapes[orient_idx]["layers"][0]
    return Polygon(layer0).area


# ---------------------------------------------------------------------------
def _parse_solution(sol: dict):
    """Return (cur_bay[bid], cur_orient[bid], horizon) from a submission solution.

    cur_bay   : block_id -> bay it was placed in
    cur_orient: block_id -> orient_idx used at placement
    horizon   : max EXIT time across the whole solution
    """
    cur_bay: dict[int, int] = {}
    cur_orient: dict[int, int] = {}
    horizon = 0
    for t_str, op_list in sol["operations"].items():
        t = int(t_str)
        for op in op_list:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                cur_bay[bid] = int(op["bay_id"])
                cur_orient[bid] = int(op.get("orient_idx", 0))
            elif op["type"] == "EXIT":
                if t > horizon:
                    horizon = t
    return cur_bay, cur_orient, horizon


# ---------------------------------------------------------------------------
def _solve_assignment(data: dict, area_time, pref, cap, cap_kind: str):
    """Min z3_raw = sum_b sum_j x[b][j]*(max_pref[b]-pref[b][j]) s.t. capacity.

    area_time : list[int]              scaled area*proc per block (for spacetime cap)
    pref      : list[list[int]]        pref[b][j] preference score
    cap       : list[int]              per-bay capacity value
    cap_kind  : "spacetime" | "count"

    Returns (z3_floor:int|None, status_str).  z3_floor is None if infeasible.
    """
    nb = len(pref)
    m = len(data["bays"])
    model = cp_model.CpModel()

    x = [[model.NewBoolVar(f"x_{b}_{j}") for j in range(m)] for b in range(nb)]
    for b in range(nb):
        model.AddExactlyOne(x[b])

    for j in range(m):
        if cap_kind == "spacetime":
            model.Add(sum(area_time[b] * x[b][j] for b in range(nb)) <= cap[j])
        else:  # count
            model.Add(sum(x[b][j] for b in range(nb)) <= cap[j])

    # objective: penalty = max_pref - chosen_pref (>=0), minimize total
    terms = []
    for b in range(nb):
        mx = max(pref[b])
        for j in range(m):
            pen = mx - pref[b][j]
            if pen:
                terms.append(pen * x[b][j])
    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = _SOLVE_TL
    solver.parameters.num_search_workers = 4
    st = solver.Solve(model)
    name = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE", cp_model.UNKNOWN: "UNKNOWN"}.get(
                st, str(st))
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return int(round(solver.ObjectiveValue())), name
    return None, name


# ---------------------------------------------------------------------------
def analyze_instance(prob_idx: int):
    """Return a result dict for one set2 instance (prob_idx in 21..40)."""
    inst = os.path.normpath(
        os.path.join(THIS, "..", "instances", "train", f"prob_{prob_idx}.json"))
    real = os.path.join(THIS, f"real_prob_{prob_idx}.json")

    data = json.load(open(inst, encoding="utf-8"))
    sol = json.load(open(real, encoding="utf-8"))
    blocks = data["blocks"]
    m = len(data["bays"])
    nb = len(blocks)
    w3 = data.get("weights", {}).get("w3", 1.0)

    # --- current z3 from the OFFICIAL checker -----------------------------
    r = _utils.check_feasibility(data, sol)
    z3_cur = r.get("obj3")

    cur_bay, cur_orient, horizon = _parse_solution(sol)

    # --- per-block scaled area*proc + preference table --------------------
    pref = [list(map(int, blocks[b]["bay_preferences"])) for b in range(nb)]
    area_time = []
    for b in range(nb):
        o = cur_orient.get(b, 0)
        a = _footprint_area(blocks[b], o)
        proc = blocks[b]["processing_time"]
        area_time.append(int(round(a * proc * _AREA_SCALE)))

    # --- SPACE-TIME capacity: W*H*horizon (scaled) ------------------------
    cap_st = [int(data["bays"][j]["width"] * data["bays"][j]["height"]
                  * horizon * _AREA_SCALE) for j in range(m)]

    # --- COUNT capacity: ceil(1.15 * current_count[j]) --------------------
    cur_count = [0] * m
    for b, j in cur_bay.items():
        if 0 <= j < m:
            cur_count[j] += 1
    cap_ct = [math.ceil(1.15 * cur_count[j]) for j in range(m)]

    z3_st, st_st = _solve_assignment(data, area_time, pref, cap_st, "spacetime")
    z3_ct, st_ct = _solve_assignment(data, area_time, pref, cap_ct, "count")

    gap_st = (z3_cur - z3_st) if (z3_cur is not None and z3_st is not None) else None
    gap_ct = (z3_cur - z3_ct) if (z3_cur is not None and z3_ct is not None) else None

    return {
        "prob": prob_idx,
        "nb": nb, "m": m,
        "z3_cur": z3_cur,
        "z3_st": z3_st, "z3_ct": z3_ct,
        "gap_st": gap_st, "gap_ct": gap_ct,
        "w3": w3,
        "w3_gap_ct": (w3 * gap_ct) if gap_ct is not None else None,
        "st_status": st_st, "ct_status": st_ct,
    }


# ---------------------------------------------------------------------------
def _fmt(v, intify=True):
    if v is None:
        return "  --"
    if intify:
        return f"{int(round(v)):,}"
    return f"{v:.0f}"


def main():
    probs = list(range(21, 41))
    print("=" * 118)
    print("z3 REASSIGNMENT FLOOR (CP-SAT pure-assignment lower bound on z3) -- set2")
    print("  space-time floor = OPTIMISTIC lower bound (assumes perfect packing) "
          "-> gap is UPPER bound on recoverable z3")
    print("  count+15% floor  = REALISTIC estimate (cap = ceil(1.15 * current "
          "blocks/bay))")
    print("=" * 118)
    hdr = (f"{'prob':>4} | {'z3_cur':>10} | {'z3_flr(ST)':>11} | "
           f"{'z3_flr(CT)':>11} | {'gap_ST':>10} | {'gap_CT':>10} | "
           f"{'w3':>8} | {'w3*gapCT':>14} | st/ct")
    print(hdr)
    print("-" * 118)

    tot_w3gap_ct = 0.0
    tot_gap_st = 0.0
    tot_gap_ct = 0.0
    rows = []
    all_opt = True
    for p in probs:
        res = analyze_instance(p)
        rows.append(res)
        if res["st_status"] != "OPTIMAL" or res["ct_status"] != "OPTIMAL":
            all_opt = False
        if res["w3_gap_ct"] is not None:
            tot_w3gap_ct += res["w3_gap_ct"]
        if res["gap_st"] is not None:
            tot_gap_st += res["gap_st"]
        if res["gap_ct"] is not None:
            tot_gap_ct += res["gap_ct"]
        print(f"{res['prob']:>4} | {_fmt(res['z3_cur']):>10} | "
              f"{_fmt(res['z3_st']):>11} | {_fmt(res['z3_ct']):>11} | "
              f"{_fmt(res['gap_st']):>10} | {_fmt(res['gap_ct']):>10} | "
              f"{_fmt(res['w3']):>8} | {_fmt(res['w3_gap_ct']):>14} | "
              f"{res['st_status'][:1]}/{res['ct_status'][:1]}")

    print("-" * 118)
    print(f"{'TOT':>4} | {'':>10} | {'':>11} | {'':>11} | "
          f"{_fmt(tot_gap_st):>10} | {_fmt(tot_gap_ct):>10} | {'':>8} | "
          f"{_fmt(tot_w3gap_ct):>14} |")
    print("=" * 118)
    print()
    print("HONEST recoverable-obj estimate (count+15% realistic model):")
    print(f"  sum over set2 of  w3 * (z3_cur - z3_floor_count)  =  "
          f"{tot_w3gap_ct:,.0f}")
    print(f"  (optimistic space-time gap in raw z3 units = {tot_gap_st:,.0f}; "
          f"realistic count gap in raw z3 units = {tot_gap_ct:,.0f})")
    print()
    print("NOTE: capacities are APPROXIMATIONS of the NP-hard packing problem. "
          "The space-time")
    print("      floor is OPTIMISTIC (true lower bound on z3); count+15% is the "
          "realistic estimate.")
    if all_opt:
        print("CP-SAT: all assignment models solved to OPTIMAL.")
    else:
        print("CP-SAT: WARNING -- not all models reached OPTIMAL (see st/ct "
              "column).")


if __name__ == "__main__":
    main()
