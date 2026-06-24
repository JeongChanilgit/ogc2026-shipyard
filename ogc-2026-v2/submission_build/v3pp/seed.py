"""
seed.py -- build a full global seed solution (per-bay greedy) and evaluate it
with the OFFICIAL feasibility checker.

The seed reuses the exact per-bay greedy that xreopt uses (build_subset ->
seed_order("edd") -> simulate(allow_stack=False, fit=True)), but runs it for
EVERY bay that has >=1 preferred block, yielding a complete global solution.

Public API:
    make_seed(inst_path, scale=2)      -> (bays_placed, data)
    serialize(bays_placed)             -> solution_dict
    global_eval(data, bays_placed)     -> {feasible, obj, z1, z2, z3, stage, violations}
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
# NOTE: as a v3pp package module, cross-imports are package-relative; we do NOT
# insert THIS onto sys.path (that would shadow the top-level v2 modules).
from .temporal_pack import build_subset, seed_order, simulate  # noqa: E402
import utils as _utils                                        # noqa: E402


# ---------------------------------------------------------------------------
def make_seed(inst_path: str, scale: int = 2):
    """Per-bay greedy layout for ALL preferred bays -> full global seed.

    Returns (bays_placed, data):
      bays_placed : {bay_id -> placed_list}
                    each placed element = {id, sh, x, y, orient, entry, exit, world}
      data        : the loaded instance dict
    """
    data = json.load(open(inst_path, encoding="utf-8"))
    blocks = data["blocks"]
    m = len(data["bays"])

    # preferred bay per block = argmax_j bay_preferences[j]
    pref = [
        max(range(m), key=lambda j: blocks[i]["bay_preferences"][j])
        for i in range(len(blocks))
    ]

    bays_placed: dict[int, list] = {}
    for j in range(m):
        if pref.count(j) == 0:
            continue
        sub = build_subset(inst_path, j, scale, geom="poly")
        order = seed_order(sub, "edd")
        placed, _z1 = simulate(sub, order, allow_stack=False, fit=True)
        bays_placed[j] = placed

    return bays_placed, data


# ---------------------------------------------------------------------------
def serialize(bays_placed: dict) -> dict:
    """{bay_id -> placed_list} -> {"operations": {str_time: [op, ...]}}.

    For each placed block: one ENTRY op (carries placement) at int(entry) and
    one EXIT op at int(exit).  Within a timestamp, EXIT ops sort before ENTRY
    ops (official Stage-5 ordering).  Dict keys are sorted by int(time).
    """
    ops: dict[str, list] = {}
    for j, placed in bays_placed.items():
        for p in placed:
            et = str(int(p["entry"]))
            xt = str(int(p["exit"]))
            ops.setdefault(et, []).append({
                "type": "ENTRY", "block_id": p["id"], "bay_id": j,
                "x": p["x"], "y": p["y"], "orient_idx": p["orient"],
            })
            ops.setdefault(xt, []).append({
                "type": "EXIT", "block_id": p["id"], "bay_id": j,
            })
    # within a timestamp: EXIT before ENTRY
    for t in ops:
        ops[t].sort(key=lambda o: 0 if o["type"] == "EXIT" else 1)
    # sort timestamps numerically
    ops_s = {k: ops[k] for k in sorted(ops, key=lambda s: int(s))}
    return {"operations": ops_s}


# ---------------------------------------------------------------------------
def global_eval(data: dict, bays_placed: dict) -> dict:
    """Serialize + run the OFFICIAL checker; return a compact result dict.

    feasible = (objective is not None and no violations).
    """
    sol = serialize(bays_placed)
    r = _utils.check_feasibility(data, sol)
    obj = r.get("objective")
    viols = r.get("violations", [])
    feasible = (obj is not None) and (len(viols) == 0)
    return {
        "feasible": feasible,
        "obj": obj,
        "z1": r.get("obj1"),
        "z2": r.get("obj2"),
        "z3": r.get("obj3"),
        "stage": r.get("stage"),
        "violations": viols,
    }


__all__ = ["make_seed", "serialize", "global_eval"]
