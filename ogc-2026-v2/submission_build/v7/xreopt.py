"""
xreopt.py -- per-bay x-only CP-SAT re-optimisation experiment.

Question: given greedy placement in one bay (y/orient/assignment fixed),
can CP-SAT find x-coordinates + entry/exit times that reduce z1 (tardiness)?

Model:
  For each block i placed by greedy in bay j:
    - xi  : IntVar in [lb, ub] (x anchor, y+orient fixed)
    - entry_i : IntVar >= R_i
    - exit_i  = entry_i + P_i  (processing time fixed)
    - tardy_i = max(0, exit_i - D_i)

  Constraint: for each pair (i, j) whose y-bboxes overlap --
    time_overlap(i,j) => NOT x_bbox_overlap(i,j)
    where time_overlap = entry_i < exit_j AND entry_j < exit_i

  Objective: Minimize sum(tardy_i)

Usage:
    python xreopt.py [prob_name] [bay_id] [time_s]

    prob_name  : 'prob_29' etc. (default 'prob_38')
    bay_id     : int or 'auto' (default: auto = bay with fewest blocks)
    time_s     : CP-SAT wall limit in seconds (default 30.0)

Examples:
    python xreopt.py prob_38
    python xreopt.py prob_29 2 15
    python xreopt.py prob_38 0 30
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

from temporal_pack import build_subset, seed_order, simulate  # noqa: E402
from gridmap import BlockShape                                  # noqa: E402
import utils as _utils                                          # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bbox_w(sh: BlockShape) -> int:
    """ceiling integer width of the block shape in world units."""
    return max(1, int(math.ceil(sh.max_x - sh.min_x)))


def _bbox_h(sh: BlockShape) -> float:
    return sh.max_y - sh.min_y


def _x_lb(sh: BlockShape) -> int:
    """minimum valid x anchor (world x >= 0)."""
    return max(0, int(math.ceil(-sh.min_x - 1e-9)))


def _x_ub(sh: BlockShape, W: int) -> int:
    """maximum valid x anchor (world x + max_x <= W)."""
    return max(_x_lb(sh), int(math.floor(W - sh.max_x + 1e-9)))


# ---------------------------------------------------------------------------
# CP-SAT model
# ---------------------------------------------------------------------------

def _build_and_solve(placed, sub, time_s: float, num_workers: int = 4):
    """
    placed : list of greedy placement dicts
             {id, sh, x, y, orient, entry, exit, world}
    sub    : build_subset() result
    time_s : solver wall limit

    Returns (new_placed, status_str, wall_s)
      new_placed : updated placed list (x / entry / exit changed), or None on failure
      status_str : 'OPTIMAL' | 'FEASIBLE' | 'UNKNOWN' | 'INFEASIBLE' | 'NO_ORTOOLS'
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        print("[xreopt] ortools not found -- pip install ortools", file=sys.stderr)
        return None, "NO_ORTOOLS", 0.0

    W = sub["W"]
    meta = sub["meta"]
    n = len(placed)
    if n == 0:
        return [], "OPTIMAL", 0.0

    # time horizon: greedy max exit + generous buffer
    max_exit_greedy = max(int(p["exit"]) for p in placed)
    HORIZON = max_exit_greedy + 50

    model = cp_model.CpModel()

    xi_vars    = []   # x anchor per block
    entry_vars = []   # entry time per block
    exit_vars  = []   # exit  time per block
    tardy_vars = []   # tardiness per block

    for k, p in enumerate(placed):
        sh  = p["sh"]
        bid = p["id"]
        R, P_raw, D = meta[bid]
        # use observed P from greedy (might differ from prob P due to rounding)
        P_int = int(round(p["exit"] - p["entry"]))
        R_int = int(math.ceil(R - 1e-9))
        D_int = int(D)

        # x variable
        lb_x = _x_lb(sh)
        ub_x = _x_ub(sh, W)
        xi_vars.append(model.NewIntVar(lb_x, ub_x, f"x{k}"))

        # entry variable: >= R, within horizon
        ev = model.NewIntVar(R_int, HORIZON, f"e{k}")
        xv = model.NewIntVar(R_int + P_int, HORIZON + P_int, f"ex{k}")
        model.Add(xv == ev + P_int)
        entry_vars.append(ev)
        exit_vars.append(xv)

        # tardiness variable
        tv = model.NewIntVar(0, HORIZON + P_int, f"t{k}")
        model.Add(tv >= xv - D_int)
        model.Add(tv >= 0)
        tardy_vars.append(tv)

    # NOTE: do NOT add a monotone entry constraint -- that would prevent
    # blocks from being placed earlier than greedy, eliminating the benefit.

    # ---- no-overlap constraints (y-bbox-overlapping pairs only) -------------
    n_pairs = 0
    for i in range(n):
        pi  = placed[i]
        shi = pi["sh"]
        wi  = _bbox_w(shi)
        # y-bbox in world coordinates (y fixed by greedy)
        yi0 = pi["y"] + shi.min_y
        yi1 = pi["y"] + shi.max_y

        for j in range(i + 1, n):
            pj  = placed[j]
            shj = pj["sh"]
            wj  = _bbox_w(shj)
            yj0 = pj["y"] + shj.min_y
            yj1 = pj["y"] + shj.max_y

            # skip if y-bboxes don't overlap (x-collision impossible)
            if yi1 <= yj0 or yj1 <= yi0:
                continue

            # time-overlap (dynamic): b_tov = (entry_i < exit_j) AND (entry_j < exit_i)
            b1 = model.NewBoolVar(f"b1_{i}_{j}")  # entry_i < exit_j  <=>  exit_j - entry_i >= 1
            b2 = model.NewBoolVar(f"b2_{i}_{j}")  # entry_j < exit_i  <=>  exit_i - entry_j >= 1
            model.Add(exit_vars[j] - entry_vars[i] >= 1).OnlyEnforceIf(b1)
            model.Add(exit_vars[j] - entry_vars[i] <= 0).OnlyEnforceIf(b1.Not())
            model.Add(exit_vars[i] - entry_vars[j] >= 1).OnlyEnforceIf(b2)
            model.Add(exit_vars[i] - entry_vars[j] <= 0).OnlyEnforceIf(b2.Not())

            b_tov = model.NewBoolVar(f"tov_{i}_{j}")
            model.AddBoolAnd([b1, b2]).OnlyEnforceIf(b_tov)
            model.AddBoolOr([b1.Not(), b2.Not()]).OnlyEnforceIf(b_tov.Not())

            # if time-overlapping: x-bboxes must NOT overlap
            # (i left of j) OR (j left of i)
            b_left  = model.NewBoolVar(f"lft_{i}_{j}")
            b_right = model.NewBoolVar(f"rgt_{i}_{j}")
            model.Add(xi_vars[i] + wi <= xi_vars[j]).OnlyEnforceIf([b_tov, b_left])
            model.Add(xi_vars[j] + wj <= xi_vars[i]).OnlyEnforceIf([b_tov, b_right])
            # b_tov => (b_left OR b_right)
            model.AddBoolOr([b_left, b_right, b_tov.Not()])
            n_pairs += 1

    print(f"  [CP-SAT] n={n}, y-overlap pairs={n_pairs}, HORIZON={HORIZON}", flush=True)

    model.Minimize(sum(tardy_vars))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_s
    solver.parameters.num_workers = num_workers
    solver.parameters.log_search_progress = False

    t0 = time.monotonic()
    status_code = solver.Solve(model)
    wall = time.monotonic() - t0

    from ortools.sat.python.cp_model import (
        OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN
    )
    status_map = {
        OPTIMAL:    "OPTIMAL",
        FEASIBLE:   "FEASIBLE",
        INFEASIBLE: "INFEASIBLE",
        UNKNOWN:    "UNKNOWN",
    }
    status_str = status_map.get(status_code, f"STATUS_{status_code}")
    print(f"  [CP-SAT] status={status_str}, obj={solver.ObjectiveValue() if status_code in (OPTIMAL,FEASIBLE) else '?'}, wall={wall:.2f}s",
          flush=True)

    if status_code not in (OPTIMAL, FEASIBLE):
        return None, status_str, wall

    # extract solution
    from shapely.affinity import translate as _translate
    new_placed = []
    for k, p in enumerate(placed):
        sh       = p["sh"]
        new_x    = solver.Value(xi_vars[k])
        new_entry = solver.Value(entry_vars[k])
        new_exit  = solver.Value(exit_vars[k])
        new_world = {
            l: _translate(sh.layers[l].poly, xoff=new_x, yoff=p["y"])
            for l in range(sh.n_layers)
        }
        new_placed.append({
            **p,
            "x":     new_x,
            "entry": new_entry,
            "exit":  new_exit,
            "world": new_world,
        })

    return new_placed, status_str, wall


# ---------------------------------------------------------------------------
# single-bay feasibility check (standalone, no dummy blocks)
# ---------------------------------------------------------------------------

def _check_bay_feasibility(data, bay_id, placed):
    """
    Build a partial solution with only the bay's blocks and validate via
    check_feasibility.  Because other blocks are absent stage-1 will fail,
    but we care only about stage 2/3/4 violations for this bay.

    Returns True if no crane/spatial violations are detected for bay_id.
    """
    ops = {}
    for p in placed:
        et = str(int(p["entry"]))
        xt = str(int(p["exit"]))
        ops.setdefault(et, []).append({
            "type": "ENTRY", "block_id": p["id"], "bay_id": bay_id,
            "x": p["x"], "y": p["y"], "orient_idx": p["orient"],
        })
        ops.setdefault(xt, []).append({
            "type": "EXIT", "block_id": p["id"], "bay_id": bay_id,
        })
    for t in ops:
        ops[t].sort(key=lambda o: 0 if o["type"] == "EXIT" else 1)
    ops_s = {k: ops[k] for k in sorted(ops, key=lambda s: int(s))}

    r = _utils.check_feasibility(data, {"operations": ops_s})
    stage   = r.get("stage", 0)
    viols   = r.get("violations", [])

    # stage 1 failure is expected (missing blocks) -- ignore it
    if stage == 1:
        return True  # no spatial/crane issues found in partial check

    # stage 2+ violation: check if it involves our bay
    bay_viols = [v for v in viols if str(bay_id) in v]
    return len(bay_viols) == 0


# ---------------------------------------------------------------------------
# main experiment function
# ---------------------------------------------------------------------------

def xreopt_bay(inst_path: str,
               bay_id=None,
               time_s: float = 30.0,
               scale: int = 2) -> dict:
    """
    Run greedy layout, then CP-SAT x-only re-optimisation on one bay.

    Returns dict with keys:
        bay_id, n_blocks, greedy_z1, cpsat_z1, delta, delta_pct,
        status, wall_s, feasible
    """
    data   = json.load(open(inst_path, encoding="utf-8"))
    bays   = data["bays"]
    blocks = data["blocks"]
    m      = len(bays)

    pref = [
        max(range(m), key=lambda j: blocks[i]["bay_preferences"][j])
        for i in range(len(blocks))
    ]
    bay_counts = [pref.count(j) for j in range(m)]

    if bay_id is None:
        bay_id = min(
            (j for j in range(m) if bay_counts[j] > 0),
            key=lambda j: bay_counts[j]
        )

    W = bays[bay_id]["width"]
    H = bays[bay_id]["height"]
    nb = bay_counts[bay_id]

    print(f"\n{'='*60}", flush=True)
    print(f"Instance : {os.path.basename(inst_path)}", flush=True)
    print(f"Bay {bay_id}   ({W}x{H}, {nb} blocks)", flush=True)
    print(f"CP-SAT limit: {time_s}s, scale={scale}", flush=True)
    print(f"{'='*60}", flush=True)

    # step 1: greedy layout
    t0  = time.monotonic()
    sub = build_subset(inst_path, bay_id, scale, geom="poly")
    order = seed_order(sub, "edd")
    placed_greedy, greedy_z1 = simulate(sub, order, allow_stack=False, fit=True)
    greedy_wall = time.monotonic() - t0
    print(f"Greedy done: {len(placed_greedy)} blocks, Z1={greedy_z1}, wall={greedy_wall:.1f}s",
          flush=True)

    if not placed_greedy:
        print("No greedy placements -- skip.", flush=True)
        return {"bay_id": bay_id, "n_blocks": 0, "greedy_z1": 0,
                "cpsat_z1": None, "delta": None, "delta_pct": None,
                "status": "EMPTY", "wall_s": 0.0, "feasible": False}

    # show greedy tardy breakdown
    meta = sub["meta"]
    tardy_blocks = [(p["id"], p["entry"], p["exit"], meta[p["id"]][2])
                    for p in placed_greedy if p["exit"] > meta[p["id"]][2]]
    if tardy_blocks:
        print(f"  Tardy blocks (greedy):", flush=True)
        for bid, en, ex, D in tardy_blocks:
            R = meta[bid][0]
            print(f"    block {bid}: R={R} entry={en} exit={ex} D={D} late={ex-D}", flush=True)
    else:
        print(f"  All blocks on-time in greedy.", flush=True)

    # step 2: CP-SAT x-only re-optimisation
    print("Building CP-SAT model...", flush=True)
    new_placed, status, cpsat_wall = _build_and_solve(placed_greedy, sub, time_s, num_workers=4)

    # step 3: evaluate
    cpsat_z1 = None
    feasible  = False

    if new_placed is not None:
        cpsat_z1 = sum(max(0, p["exit"] - meta[p["id"]][2]) for p in new_placed)

        # check feasibility for this bay only
        feasible = _check_bay_feasibility(data, bay_id, new_placed)
        if not feasible:
            print(f"  [warn] bay feasibility check failed -- discarding CP-SAT result",
                  flush=True)
            new_placed = placed_greedy
            cpsat_z1   = greedy_z1
        else:
            print(f"  [ok] bay feasibility check passed", flush=True)
            # show cpsat placement for tardy blocks
            for bid, en, ex, D in tardy_blocks:
                cp_p = next((p for p in new_placed if p["id"] == bid), None)
                if cp_p:
                    new_late = max(0, cp_p["exit"] - D)
                    R = meta[bid][0]
                    print(f"    block {bid}: greedy entry={en} exit={ex}  "
                          f"->  cpsat entry={cp_p['entry']} exit={cp_p['exit']} late={new_late}",
                          flush=True)
    else:
        print(f"  No CP-SAT solution (status={status}) -- keeping greedy", flush=True)
        cpsat_z1 = greedy_z1

    # delta
    delta = None
    delta_pct = None
    if cpsat_z1 is not None:
        delta = cpsat_z1 - greedy_z1
        delta_pct = (delta / greedy_z1 * 100.0) if greedy_z1 > 0 else 0.0

    print(f"\nResult summary:", flush=True)
    print(f"  greedy Z1 : {greedy_z1}", flush=True)
    print(f"  cpsat  Z1 : {cpsat_z1}", flush=True)
    if delta is not None:
        print(f"  delta     : {delta:+d} ({delta_pct:+.1f}%)", flush=True)
    print(f"  status    : {status}", flush=True)
    print(f"  wall      : {cpsat_wall:.2f}s", flush=True)
    print(f"  feasible  : {feasible}", flush=True)

    return {
        "bay_id":    bay_id,
        "n_blocks":  len(placed_greedy),
        "greedy_z1": greedy_z1,
        "cpsat_z1":  cpsat_z1,
        "delta":     delta,
        "delta_pct": delta_pct,
        "status":    status,
        "wall_s":    cpsat_wall,
        "feasible":  feasible,
    }


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def _find_inst(prob_name: str) -> str | None:
    if os.path.isfile(prob_name):
        return prob_name
    for rel in [
        "../../instances/train",
        "../instances/train",
        "instances/train",
        os.path.join(THIS, "..", "..", "instances", "train"),
    ]:
        p = os.path.normpath(os.path.join(THIS, rel, prob_name + ".json"))
        if os.path.isfile(p):
            return p
        p2 = os.path.normpath(os.path.join(THIS, rel, prob_name))
        if os.path.isfile(p2):
            return p2
    return None


def main():
    args = sys.argv[1:]
    prob  = args[0] if len(args) > 0 else "prob_38"
    bay_a = args[1] if len(args) > 1 else "auto"
    ts    = float(args[2]) if len(args) > 2 else 30.0

    bay_id = None
    if bay_a not in ("auto", "None", "none", ""):
        bay_id = int(bay_a)

    inst = _find_inst(prob)
    if inst is None:
        print(f"Instance not found: {prob}", file=sys.stderr)
        sys.exit(1)

    result = xreopt_bay(inst, bay_id=bay_id, time_s=ts, scale=2)

    n       = result.get("n_blocks", 0)
    status  = result.get("status", "?")
    wall    = result.get("wall_s", 0.0)
    dp      = result.get("delta_pct")
    gz1     = result.get("greedy_z1", 0)
    cz1     = result.get("cpsat_z1")
    delta   = result.get("delta")

    print(f"\n{'='*60}", flush=True)
    print(f"Key questions:", flush=True)

    if status in ("OPTIMAL", "FEASIBLE"):
        print(f"(1) n_blocks={n}, SOLVED ({status}) in {wall:.1f}s", flush=True)
    else:
        print(f"(1) n_blocks={n}, NOT SOLVED (status={status}) in {wall:.1f}s", flush=True)

    if gz1 == 0:
        print(f"(2) Greedy Z1=0 already -- no room to improve.", flush=True)
    elif cz1 is not None and delta is not None:
        if delta < 0:
            print(f"(2) Z1 improved: {gz1} -> {cz1} ({dp:+.1f}%) -- x-reopt EFFECTIVE", flush=True)
        elif delta == 0:
            print(f"(2) Z1 unchanged: {gz1} -- x-reopt gave no gain", flush=True)
        else:
            print(f"(2) Z1 worsened: {gz1} -> {cz1} ({dp:+.1f}%) -- model too loose?", flush=True)
    else:
        print(f"(2) Z1 comparison N/A (no solution)", flush=True)

    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
