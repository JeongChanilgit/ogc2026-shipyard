"""
coorddesc.py -- block coordinate-descent CP-SAT polish.

Per-bay, per-axis (x / y / t) spatial+timing CP-SAT re-optimisation cycled
until convergence.  Each move is gated by the FULL official objective: a trial
is accepted ONLY IF it stays feasible AND strictly lowers obj.  Therefore the
output is provably never-worse than the input seed.

Since z2 (imbalance) and z3 (preference) depend only on which blocks live in
which bay, per-bay x/y/t moves change ONLY z1 -- but the gate is always the
full obj via the official checker, so correctness is never assumed.

Public API:
    coorddesc(data, bays_placed, inst_path, total_time_s=60.0, scale=2,
              cycle=("x","y","t"), max_rounds=8) -> (best_bays_placed, log)
"""
from __future__ import annotations

import math
import os
import sys
import time
from copy import deepcopy

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

from temporal_pack import build_subset  # noqa: E402
from xreopt_ref import _bbox_w, _bbox_h, _x_lb, _x_ub  # noqa: E402


# ---------------------------------------------------------------------------
def _solve_axis(placed, sub, axis, time_s, bay_H, num_workers=4):
    """Parameterized spatial+timing CP-SAT for one bay along one axis.

    axis="x": free x anchor + entry/exit; y fixed; a pair is constrained only
              when y-bboxes overlap; disjunction on x via bbox widths.
    axis="y": MIRROR -- free y anchor + entry/exit; x fixed; a pair is
              constrained only when x-bboxes overlap; disjunction on y via bbox
              heights.
    axis="t": pure timing -- positions pinned (x lb=ub), only entry/exit free.

    Returns (new_placed_or_None, status_str, wall).
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None, "NO_ORTOOLS", 0.0
    from shapely.affinity import translate

    W = sub["W"]
    meta = sub["meta"]
    n = len(placed)
    if n == 0:
        return [], "OPTIMAL", 0.0

    max_exit_greedy = max(int(p["exit"]) for p in placed)
    HORIZON = max_exit_greedy + 50

    model = cp_model.CpModel()

    pos_vars = []     # x anchor (axis x/t) or y anchor (axis y)
    entry_vars = []
    exit_vars = []
    tardy_vars = []

    for k, p in enumerate(placed):
        sh = p["sh"]
        bid = p["id"]
        R, _P_raw, D = meta[bid]
        P_int = int(round(p["exit"] - p["entry"]))
        R_int = int(math.ceil(R - 1e-9))
        D_int = int(D)

        if axis == "y":
            lb = max(0, int(math.ceil(-sh.min_y - 1e-9)))
            ub = max(lb, int(math.floor(bay_H - sh.max_y + 1e-9)))
            pos_vars.append(model.NewIntVar(lb, ub, f"y{k}"))
        elif axis == "t":
            # pin position to its current x (domain collapsed)
            cur = int(p["x"])
            pos_vars.append(model.NewIntVar(cur, cur, f"xfix{k}"))
        else:  # axis == "x"
            lb = _x_lb(sh)
            ub = _x_ub(sh, W)
            pos_vars.append(model.NewIntVar(lb, ub, f"x{k}"))

        ev = model.NewIntVar(R_int, HORIZON, f"e{k}")
        xv = model.NewIntVar(R_int + P_int, HORIZON + P_int, f"ex{k}")
        model.Add(xv == ev + P_int)
        entry_vars.append(ev)
        exit_vars.append(xv)

        tv = model.NewIntVar(0, HORIZON + P_int, f"t{k}")
        model.Add(tv >= xv - D_int)
        model.Add(tv >= 0)
        tardy_vars.append(tv)

    # ---- no-overlap constraints (cross-axis-bbox-overlapping pairs only) ----
    for i in range(n):
        pi = placed[i]
        shi = pi["sh"]

        if axis == "y":
            # constrain only when x-bboxes overlap; disjunction on y via heights
            si = max(1, int(math.ceil(_bbox_h(shi))))
            ai0 = pi["x"] + shi.min_x          # x-bbox of i (x fixed)
            ai1 = pi["x"] + shi.max_x
        else:  # x or t
            # constrain only when y-bboxes overlap; disjunction on x via widths
            si = _bbox_w(shi)
            ai0 = pi["y"] + shi.min_y          # y-bbox of i (y fixed)
            ai1 = pi["y"] + shi.max_y

        for j in range(i + 1, n):
            pj = placed[j]
            shj = pj["sh"]

            if axis == "y":
                sj = max(1, int(math.ceil(_bbox_h(shj))))
                aj0 = pj["x"] + shj.min_x
                aj1 = pj["x"] + shj.max_x
            else:
                sj = _bbox_w(shj)
                aj0 = pj["y"] + shj.min_y
                aj1 = pj["y"] + shj.max_y

            # skip pair if the fixed-axis bboxes don't overlap
            if ai1 <= aj0 or aj1 <= ai0:
                continue

            # time-overlap reification (IDENTICAL to x-model)
            b1 = model.NewBoolVar(f"b1_{i}_{j}")
            b2 = model.NewBoolVar(f"b2_{i}_{j}")
            model.Add(exit_vars[j] - entry_vars[i] >= 1).OnlyEnforceIf(b1)
            model.Add(exit_vars[j] - entry_vars[i] <= 0).OnlyEnforceIf(b1.Not())
            model.Add(exit_vars[i] - entry_vars[j] >= 1).OnlyEnforceIf(b2)
            model.Add(exit_vars[i] - entry_vars[j] <= 0).OnlyEnforceIf(b2.Not())

            b_tov = model.NewBoolVar(f"tov_{i}_{j}")
            model.AddBoolAnd([b1, b2]).OnlyEnforceIf(b_tov)
            model.AddBoolOr([b1.Not(), b2.Not()]).OnlyEnforceIf(b_tov.Not())

            # if time-overlapping: free-axis bboxes must NOT overlap
            b_lo = model.NewBoolVar(f"lo_{i}_{j}")
            b_hi = model.NewBoolVar(f"hi_{i}_{j}")
            model.Add(pos_vars[i] + si <= pos_vars[j]).OnlyEnforceIf([b_tov, b_lo])
            model.Add(pos_vars[j] + sj <= pos_vars[i]).OnlyEnforceIf([b_tov, b_hi])
            model.AddBoolOr([b_lo, b_hi, b_tov.Not()])

    model.Minimize(sum(tardy_vars))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.1, float(time_s))
    solver.parameters.num_workers = num_workers
    solver.parameters.log_search_progress = False

    t0 = time.monotonic()
    status_code = solver.Solve(model)
    wall = time.monotonic() - t0

    from ortools.sat.python.cp_model import OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN
    status_map = {OPTIMAL: "OPTIMAL", FEASIBLE: "FEASIBLE",
                  INFEASIBLE: "INFEASIBLE", UNKNOWN: "UNKNOWN"}
    status_str = status_map.get(status_code, f"STATUS_{status_code}")

    if status_code not in (OPTIMAL, FEASIBLE):
        return None, status_str, wall

    new_placed = []
    for k, p in enumerate(placed):
        sh = p["sh"]
        new_entry = solver.Value(entry_vars[k])
        new_exit = solver.Value(exit_vars[k])
        if axis == "y":
            new_x = p["x"]
            new_y = solver.Value(pos_vars[k])
        else:  # x or t  (t pinned x to current via collapsed domain)
            new_x = solver.Value(pos_vars[k])
            new_y = p["y"]
        new_world = {
            l: translate(sh.layers[l].poly, xoff=new_x, yoff=new_y)
            for l in range(sh.n_layers)
        }
        new_placed.append({
            **p,
            "x": new_x,
            "y": new_y,
            "entry": new_entry,
            "exit": new_exit,
            "world": new_world,
        })

    return new_placed, status_str, wall


# ---------------------------------------------------------------------------
def coorddesc(data, bays_placed, inst_path, total_time_s=60.0, scale=2,
              cycle=("x", "y", "t"), max_rounds=8):
    """Block coordinate-descent over bays x axes, full-obj gated.

    Accepts a per-bay/per-axis CP-SAT move ONLY IF it keeps the global
    solution feasible AND strictly improves the full objective.  Provably
    never-worse than the input seed.

    Returns (best_bays_placed, log) where log is a list of per-move rows.
    """
    from seed import global_eval

    current = deepcopy(bays_placed)
    base = global_eval(data, current)
    log: list[dict] = []

    if not base["feasible"]:
        log.append({"note": "seed infeasible -- no descent",
                    "obj_before": base["obj"], "stage": base["stage"],
                    "violations": base["violations"][:3]})
        return current, log

    cur_obj = base["obj"]

    # bays that actually have blocks
    active_bays = [j for j in current if current[j]]
    n_bays = max(1, len(active_bays))

    # precompute per-bay subset + bay height
    sub_by_bay = {}
    H_by_bay = {}
    for j in active_bays:
        sub_by_bay[j] = build_subset(inst_path, j, scale, geom="poly")
        H_by_bay[j] = data["bays"][j]["height"]

    start = time.monotonic()
    deadline = start + total_time_s

    for rnd in range(max_rounds):
        if time.monotonic() > deadline:
            break
        round_accepted = 0

        for j in active_bays:
            for axis in cycle:
                if time.monotonic() > deadline:
                    break

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                per_pass = max(4.0, total_time_s /
                               (max_rounds * len(cycle) * n_bays))
                budget = min(per_pass, remaining)

                obj_before = cur_obj
                new_placed, status, wall = _solve_axis(
                    current[j], sub_by_bay[j], axis, budget, H_by_bay[j])

                obj_after = None
                accepted = False
                if new_placed:
                    trial = {**current, j: new_placed}
                    ev = global_eval(data, trial)
                    obj_after = ev["obj"]
                    # GATE: accept ONLY IF feasible AND strictly better
                    if ev["feasible"] and ev["obj"] < cur_obj - 1e-6:
                        current = trial
                        cur_obj = ev["obj"]
                        accepted = True
                        round_accepted += 1

                log.append({
                    "round": rnd, "bay": j, "axis": axis, "status": status,
                    "obj_before": obj_before, "obj_after": obj_after,
                    "accepted": accepted, "wall": wall,
                })

            if time.monotonic() > deadline:
                break

        # convergence: a full round with zero accepted moves
        if round_accepted == 0:
            break

    return current, log


__all__ = ["coorddesc", "_solve_axis"]
