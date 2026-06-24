"""
z3_headroom.py -- z3 recovery potential: how much z3 is z1-safe recoverable?

Measures per instance:
  z3_current       = official check_feasibility z3
  z3_floor_unconstrained = argmax-pref assignment (all blocks to best bay, ignore capacity)
  z3_floor_loadneutral  = CP-SAT: keep block COUNT per bay ≈ current, minimize z3
  z3_floor_areaneutral  = CP-SAT: keep block COUNT per bay ≈ current AND total area per bay
                           within ±10% of current, minimize z3 (z1-safe proxy)
  wrong_bay_with_slack  = wrong-bay blocks whose preferred bay has co-presence headroom

Run:
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe z3_headroom.py
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

from ortools.sat.python import cp_model
from shapely.geometry import Polygon
import utils as _utils

PYTHON = "C:/Users/peter/anaconda3/envs/ogc2025/python.exe"
INST_DIR = os.path.normpath(os.path.join(THIS, "..", "instances", "train"))
SOLVE_TL = 20.0  # seconds per CP-SAT model
AREA_SCALE = 100  # float area -> int (scale factor)
COPRES_SLACK_THR = 3  # co-presence at-or-below = "slack" in preferred bay


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _footprint_area(block: dict, orient_idx: int) -> float:
    """Layer-0 polygon area for a given orientation."""
    shapes = block["shape"]
    if not (0 <= orient_idx < len(shapes)):
        orient_idx = 0
    layer0 = shapes[orient_idx]["layers"][0]
    return Polygon(layer0).area


def _best_orient_area(block: dict) -> float:
    """Min layer-0 area over all orientations (densest packing)."""
    best = None
    for sh in block["shape"]:
        a = Polygon(sh["layers"][0]).area
        if best is None or a < best:
            best = a
    return best if best is not None else 1.0


# ---------------------------------------------------------------------------
# Parse solution
# ---------------------------------------------------------------------------

def _parse_solution(data: dict, sol: dict):
    """Return (cur_bay, cur_orient, cur_entry, cur_exit, tardiness) per block."""
    blocks = data["blocks"]
    m = len(data["bays"])
    cur_bay: dict[int, int] = {}
    cur_orient: dict[int, int] = {}
    cur_entry: dict[int, int] = {}
    cur_exit: dict[int, int] = {}

    for t_str, op_list in sol["operations"].items():
        t = int(t_str)
        for op in op_list:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                cur_bay[bid] = int(op["bay_id"])
                cur_orient[bid] = int(op.get("orient_idx", 0))
                cur_entry[bid] = t
            elif op["type"] == "EXIT":
                cur_exit[bid] = t

    # preferred bay per block
    pref_bay = {}
    for bid, blk in enumerate(blocks):
        prefs = blk["bay_preferences"]
        pref_bay[bid] = max(range(m), key=lambda j: prefs[j])

    tardiness = {}
    for bid in cur_bay:
        exit_t = cur_exit.get(bid, cur_entry.get(bid, 0) + blocks[bid]["processing_time"])
        tardiness[bid] = max(0, exit_t - blocks[bid]["due_date"])

    return cur_bay, cur_orient, cur_entry, cur_exit, pref_bay, tardiness


# ---------------------------------------------------------------------------
# z3 computation
# ---------------------------------------------------------------------------

def _z3_of_assignment(data: dict, assignment: dict[int, int]) -> float:
    """Sum_b (max_pref[b] - pref[b][bay]) for given assignment dict {bid: bay}."""
    blocks = data["blocks"]
    total = 0.0
    for bid, bj in assignment.items():
        prefs = blocks[bid]["bay_preferences"]
        total += max(prefs) - prefs[bj]
    return total


# ---------------------------------------------------------------------------
# CP-SAT assignment models
# ---------------------------------------------------------------------------

def _solve_assignment_count(data: dict, cur_counts: list[int],
                             time_s: float = SOLVE_TL) -> tuple[float | None, str, dict | None]:
    """Min z3 s.t. per-bay count == current count (load-neutral). Returns (z3, status, {bid:bay})."""
    blocks = data["blocks"]
    nb = len(blocks)
    m = len(data["bays"])
    pref = [list(map(int, blocks[b]["bay_preferences"])) for b in range(nb)]

    model = cp_model.CpModel()
    x = [[model.NewBoolVar(f"x_{b}_{j}") for j in range(m)] for b in range(nb)]
    for b in range(nb):
        model.AddExactlyOne(x[b])
    # Exact count constraint (load-neutral)
    for j in range(m):
        model.Add(sum(x[b][j] for b in range(nb)) == cur_counts[j])

    terms = []
    for b in range(nb):
        mx = max(pref[b])
        for j in range(m):
            pen = mx - pref[b][j]
            if pen:
                terms.append(pen * x[b][j])
    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_s
    solver.parameters.num_search_workers = 4
    st = solver.Solve(model)
    names = {cp_model.OPTIMAL: "OPT", cp_model.FEASIBLE: "FEAS",
             cp_model.INFEASIBLE: "INF", cp_model.UNKNOWN: "UNK"}
    sname = names.get(st, str(st))
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        z3v = float(solver.ObjectiveValue())
        asgn = {b: next(j for j in range(m) if solver.Value(x[b][j])) for b in range(nb)}
        return z3v, sname, asgn
    return None, sname, None


def _solve_assignment_areaneutral(data: dict, cur_bay: dict[int, int],
                                   cur_orient: dict[int, int],
                                   time_s: float = SOLVE_TL) -> tuple[float | None, str, dict | None]:
    """Min z3 s.t. per-bay block count == current AND per-bay total area within ±10%.
    This is the z1-safe proxy: same load + similar packing density."""
    blocks = data["blocks"]
    nb = len(blocks)
    m = len(data["bays"])
    pref = [list(map(int, blocks[b]["bay_preferences"])) for b in range(nb)]

    # Current per-bay block count
    cur_counts = [0] * m
    for b, j in cur_bay.items():
        if 0 <= j < m:
            cur_counts[j] += 1

    # Current per-bay total area (scaled)
    cur_area = [0] * m
    for b, j in cur_bay.items():
        if 0 <= j < m:
            o = cur_orient.get(b, 0)
            a = int(round(_footprint_area(blocks[b], o) * AREA_SCALE))
            cur_area[j] += a

    # Per-block area (use current orient, fallback best orient)
    block_area = []
    for b in range(nb):
        o = cur_orient.get(b, 0)
        a = int(round(_footprint_area(blocks[b], o) * AREA_SCALE))
        block_area.append(a)

    model = cp_model.CpModel()
    x = [[model.NewBoolVar(f"x_{b}_{j}") for j in range(m)] for b in range(nb)]
    for b in range(nb):
        model.AddExactlyOne(x[b])

    # Exact count per bay
    for j in range(m):
        model.Add(sum(x[b][j] for b in range(nb)) == cur_counts[j])

    # Area ±10% per bay (scaled integers)
    for j in range(m):
        if cur_area[j] > 0:
            lo = int(math.floor(cur_area[j] * 0.90))
            hi = int(math.ceil(cur_area[j] * 1.10))
            model.Add(sum(block_area[b] * x[b][j] for b in range(nb)) >= lo)
            model.Add(sum(block_area[b] * x[b][j] for b in range(nb)) <= hi)

    terms = []
    for b in range(nb):
        mx = max(pref[b])
        for j in range(m):
            pen = mx - pref[b][j]
            if pen:
                terms.append(pen * x[b][j])
    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_s
    solver.parameters.num_search_workers = 4
    st = solver.Solve(model)
    names = {cp_model.OPTIMAL: "OPT", cp_model.FEASIBLE: "FEAS",
             cp_model.INFEASIBLE: "INF", cp_model.UNKNOWN: "UNK"}
    sname = names.get(st, str(st))
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        z3v = float(solver.ObjectiveValue())
        asgn = {b: next(j for j in range(m) if solver.Value(x[b][j])) for b in range(nb)}
        return z3v, sname, asgn
    return None, sname, None


# ---------------------------------------------------------------------------
# Co-presence slack analysis
# ---------------------------------------------------------------------------

def _copresence_at_time(placed_list: list, t: int) -> int:
    """Number of blocks co-present in a bay at time t."""
    return sum(1 for p in placed_list if p["entry"] <= t < p["exit"])


def _peak_copresence(placed_list: list) -> int:
    """Peak co-presence count in a bay across all time points (event-driven)."""
    events = set()
    for p in placed_list:
        events.add(p["entry"])
        events.add(p["exit"])
    if not events:
        return 0
    return max(_copresence_at_time(placed_list, t) for t in events)


def _wrong_bay_slack_count(data: dict, sol: dict, cur_bay: dict, pref_bay: dict,
                            cur_entry: dict, cur_exit: dict) -> tuple[int, int]:
    """
    Count wrong-bay blocks whose preferred bay has slack (co-presence <= COPRES_SLACK_THR)
    during the block's own time window.
    Returns (n_slack, n_wrong) where n_slack = safe-to-move count.
    """
    blocks = data["blocks"]
    m = len(data["bays"])

    # Build per-bay placed list from solution
    bay_placed: dict[int, list] = {j: [] for j in range(m)}
    for bid, bj in cur_bay.items():
        entry = cur_entry.get(bid, 0)
        exit_t = cur_exit.get(bid, entry + blocks[bid]["processing_time"])
        bay_placed[bj].append({"entry": entry, "exit": exit_t, "id": bid})

    wrong_bids = [bid for bid, bj in cur_bay.items() if bj != pref_bay.get(bid, bj)]
    n_wrong = len(wrong_bids)
    n_slack = 0

    for bid in wrong_bids:
        pj = pref_bay.get(bid)
        if pj is None:
            continue
        entry = cur_entry.get(bid, 0)
        exit_t = cur_exit.get(bid, entry + blocks[bid]["processing_time"])
        # Check co-presence in preferred bay during this block's window
        # Sample at entry, mid, exit-1
        mid = (entry + exit_t) // 2
        check_times = sorted(set([entry, mid, max(entry, exit_t - 1)]))
        max_cp = max(_copresence_at_time(bay_placed[pj], t) for t in check_times)
        if max_cp <= COPRES_SLACK_THR:
            n_slack += 1

    return n_slack, n_wrong


# ---------------------------------------------------------------------------
# Per-instance analysis
# ---------------------------------------------------------------------------

def analyze(prob_num: int) -> dict:
    inst_path = os.path.join(INST_DIR, f"prob_{prob_num}.json")
    sol_path = os.path.join(THIS, f"real_prob_{prob_num}.json")

    data = json.load(open(inst_path, encoding="utf-8"))
    sol = json.load(open(sol_path, encoding="utf-8"))
    blocks = data["blocks"]
    nb = len(blocks)
    m = len(data["bays"])
    w = data.get("weights", {})
    w1 = w.get("w1", 1.0)
    w3 = w.get("w3", 1.0)

    # Official z3 current
    r = _utils.check_feasibility(data, sol)
    z3_cur = r.get("obj3", 0) or 0.0
    obj_cur = r.get("objective", 0) or 0.0
    z1_cur = r.get("obj1", 0) or 0.0

    cur_bay, cur_orient, cur_entry, cur_exit, pref_bay, tardiness = _parse_solution(data, sol)

    # z3 unconstrained = 0 (all to argmax pref => max_pref - max_pref = 0)
    z3_floor_unconstrained = 0.0

    # Count per bay (current)
    cur_counts = [0] * m
    for b, j in cur_bay.items():
        if 0 <= j < m:
            cur_counts[j] += 1

    # Load-neutral CP-SAT (exact count)
    t0 = time.time()
    z3_loadneutral, st_ln, asgn_ln = _solve_assignment_count(data, cur_counts)
    t_ln = time.time() - t0

    # Area-neutral CP-SAT (exact count + ±10% area = z1-safe proxy)
    t0 = time.time()
    z3_areaneutral, st_an, asgn_an = _solve_assignment_areaneutral(data, cur_bay, cur_orient)
    t_an = time.time() - t0

    # Wrong-bay slack analysis
    n_slack, n_wrong = _wrong_bay_slack_count(data, sol, cur_bay, pref_bay, cur_entry, cur_exit)

    # Recoverable z3 values
    recover_ln = (z3_cur - z3_loadneutral) if z3_loadneutral is not None else None
    recover_an = (z3_cur - z3_areaneutral) if z3_areaneutral is not None else None

    # w3-weighted recoverable obj reduction
    w3_recover_ln = w3 * recover_ln if recover_ln is not None else None
    w3_recover_an = w3 * recover_an if recover_an is not None else None

    return {
        "prob": prob_num,
        "nb": nb, "m": m,
        "w1": w1, "w3": w3,
        "obj_cur": obj_cur,
        "z1_cur": z1_cur,
        "z3_cur": z3_cur,
        "w3z3_cur": w3 * z3_cur,
        "z3_pct": 100 * w3 * z3_cur / obj_cur if obj_cur else 0,
        "z3_floor_unconstrained": z3_floor_unconstrained,
        "z3_loadneutral": z3_loadneutral,
        "st_ln": st_ln,
        "z3_areaneutral": z3_areaneutral,
        "st_an": st_an,
        "recover_ln": recover_ln,
        "recover_an": recover_an,
        "w3_recover_ln": w3_recover_ln,
        "w3_recover_an": w3_recover_an,
        "n_wrong": n_wrong,
        "n_slack": n_slack,
        "t_ln": t_ln,
        "t_an": t_an,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # z3-heavy instances + z1-heavy contrast
    z3_heavy = [36, 24, 34, 31, 28, 21, 35]
    z1_heavy = [38, 27]
    # Also add zero-z1 instances (pure z3)
    zero_z1 = [22, 29]
    probs = z3_heavy + zero_z1 + z1_heavy

    print("=" * 120)
    print("z3 HEADROOM ANALYSIS -- z1-safe recoverable z3 (set2)")
    print(f"  load-neutral  = CP-SAT: exact block count per bay, minimize z3")
    print(f"  area-neutral  = CP-SAT: exact count + per-bay area +-10%, minimize z3 (z1-safe proxy)")
    print(f"  slack-movable = wrong-bay blocks whose preferred bay has co-presence <= {COPRES_SLACK_THR}")
    print("=" * 120)

    hdr = (f"{'p':>4} | {'nb':>4} | {'obj':>11} | {'w3*z3':>9} | {'z3%':>5} | "
           f"{'z3_cur':>8} | {'z3_LN':>8} | {'z3_AN':>8} | "
           f"{'rec_LN':>8} | {'rec_AN':>8} | "
           f"{'w3*recAN':>10} | {'slk/wrg':>8} | LN/AN")
    print(hdr)
    print("-" * 120)

    rows = []
    sum_w3z3_cur = 0.0
    sum_w3_rec_ln = 0.0
    sum_w3_rec_an = 0.0

    for p in probs:
        print(f"  [prob_{p}] analyzing...", flush=True)
        res = analyze(p)
        rows.append(res)

        tag = "z3H" if p in z3_heavy else ("z1=0" if p in zero_z1 else "z1H")
        st_ln = res["st_ln"]
        st_an = res["st_an"]

        ln_str = f"{res['z3_loadneutral']:>8,.0f}" if res["z3_loadneutral"] is not None else "      --"
        an_str = f"{res['z3_areaneutral']:>8,.0f}" if res["z3_areaneutral"] is not None else "      --"
        recln_str = f"{res['recover_ln']:>8,.0f}" if res["recover_ln"] is not None else "      --"
        recan_str = f"{res['recover_an']:>8,.0f}" if res["recover_an"] is not None else "      --"
        w3recan_str = f"{res['w3_recover_an']:>10,.0f}" if res["w3_recover_an"] is not None else "        --"

        print(f"{res['prob']:>4} | {res['nb']:>4} | {res['obj_cur']:>11,.0f} | "
              f"{res['w3z3_cur']:>9,.0f} | {res['z3_pct']:>4.1f}% | "
              f"{res['z3_cur']:>8,.0f} | {ln_str} | {an_str} | "
              f"{recln_str} | {recan_str} | {w3recan_str} | "
              f"{res['n_slack']:>3}/{res['n_wrong']:<4} | {st_ln}/{st_an}  [{tag}]")

        sum_w3z3_cur += res["w3z3_cur"]
        if res["w3_recover_ln"] is not None:
            sum_w3_rec_ln += res["w3_recover_ln"]
        if res["w3_recover_an"] is not None:
            sum_w3_rec_an += res["w3_recover_an"]

    print("-" * 120)
    print(f"TOTALS (all analyzed): sum w3*z3_cur={sum_w3z3_cur:,.0f}  "
          f"sum w3*(rec_LN)={sum_w3_rec_ln:,.0f}  sum w3*(rec_AN)={sum_w3_rec_an:,.0f}")

    # z3-heavy subset totals
    sum_w3z3_zh = sum(r["w3z3_cur"] for r in rows if r["prob"] in z3_heavy)
    sum_rec_an_zh = sum(r["w3_recover_an"] for r in rows
                        if r["prob"] in z3_heavy and r["w3_recover_an"] is not None)
    sum_rec_ln_zh = sum(r["w3_recover_ln"] for r in rows
                        if r["prob"] in z3_heavy and r["w3_recover_ln"] is not None)

    print()
    print("=" * 120)
    print("SUMMARY (z3-heavy subset: prob_36,24,34,31,28,21,35)")
    print(f"  current w3*z3 = {sum_w3z3_zh:,.0f}")
    print(f"  load-neutral recovery (same block count/bay) = {sum_rec_ln_zh:,.0f}")
    print(f"  area-neutral recovery (z1-safe: same count+area) = {sum_rec_an_zh:,.0f}")

    # Judgment
    print()
    print("VERDICT:")
    if sum_rec_an_zh > 2_000_000:
        print(f"  >> z1-SAFE recoverable z3 = {sum_rec_an_zh:,.0f} ({100*sum_rec_an_zh/sum_w3z3_zh:.0f}% of w3*z3)  -- SIGNIFICANT lever")
    elif sum_rec_an_zh > 500_000:
        print(f"  >> z1-safe recovery = {sum_rec_an_zh:,.0f} -- MODERATE lever (worth pursuing)")
    else:
        print(f"  >> z1-safe recovery = {sum_rec_an_zh:,.0f} -- MARGINAL (z3 near floor)")

    # bpass comparison note
    print()
    print("NOTE: bpass already captures some load-neutral swaps (tardy+wrong-bay blocks).")
    print("  LN gap above = UPPER BOUND; actual new gain = LN_recovery - bpass_already_captured.")

    # Save results JSON
    out = os.path.join(THIS, "z3_headroom_results.json")
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nResults saved to: {out}")


if __name__ == "__main__":
    main()
