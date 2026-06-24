"""
reassign.py -- PROTOTYPE: does cutting z3 (preference deviation) by REASSIGNING
blocks to more-preferred bays actually lower the FULL objective, or does
re-packing the now-crowded preferred bays blow z1 (tardiness) back up and wipe
out the z3 gain?

Pipeline per instance:
  1. Load the current submission solution real_prob_<i>.json -> base (obj/z1/z2/z3).
  2. CP-SAT bay-REASSIGNMENT (lifted from assign_floor.py): count+15% capacity,
     minimize z3 = sum_b x[b][j]*(max_pref[b]-pref[b][j]).  -> new_assign.
  3. For EACH bay, build the per-bay packing problem for its NEW block set and
     re-pack from scratch crane-safely (temporal_pack.simulate, edd order) -> z1.
  4. global_eval the reassigned+repacked solution.  NEVER-WORSE gate (report-only):
     accepted = ev.feasible and ev.obj < base.obj.
  5. (polish=True) optional crane_repack_bay x/y passes per bay to recover z1.

The per-bay packing problem for an ARBITRARY id list is built by `_build_subset_ids`,
a variant of temporal_pack.build_subset that mirrors its `sub` structure exactly
(same meta/shapes/cm/raw keys, same build_shape + _common_masks path) but selects
blocks from an explicit id list instead of "preferred-bay" blocks.

Run (env python, 4-worker CP-SAT, from v4 dir):
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe reassign.py 38,27
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe reassign.py          # default top-5
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

from gridmap import build_shape                     # noqa: E402
from density_pack import _common_masks              # noqa: E402

_ASSIGN_TL = 15.0     # CP-SAT assignment wall (s)
_PACK_TL = 20.0       # per-bay pack budget hint (s) -- simulate is deterministic/fast
_POLISH_BAY_TL = 20.0 # crane_repack_bay cap per bay (s)
DEFAULT_PROBS = [38, 27, 39, 31, 28]


# ---------------------------------------------------------------------------
def _solve_assignment(data: dict, current_counts, time_s: float = _ASSIGN_TL):
    """CP-SAT pure bay reassignment (lifted from assign_floor._solve_assignment,
    'count' cap kind).  Returns dict {block_id: bay}.

    Model:  for each block exactly one bay; per bay
              sum_b x[b][j] <= ceil(1.15 * current_counts[j]);
            minimize  sum_b sum_j x[b][j]*(max_pref[b] - pref[b][j]).
    """
    blocks = data["blocks"]
    nb = len(blocks)
    m = len(data["bays"])
    pref = [list(map(int, blocks[b]["bay_preferences"])) for b in range(nb)]
    cap = [math.ceil(1.15 * current_counts[j]) for j in range(m)]

    model = cp_model.CpModel()
    x = [[model.NewBoolVar(f"x_{b}_{j}") for j in range(m)] for b in range(nb)]
    for b in range(nb):
        model.AddExactlyOne(x[b])
    for j in range(m):
        model.Add(sum(x[b][j] for b in range(nb)) <= cap[j])

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
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # capacity too tight (shouldn't happen: 15% slack) -> fall back to keep-current
        return None
    assign = {}
    for b in range(nb):
        for j in range(m):
            if solver.Value(x[b][j]):
                assign[b] = j
                break
    return assign


# ---------------------------------------------------------------------------
def _build_subset_ids(data: dict, bay_id: int, block_ids, scale: int = 2):
    """Variant of temporal_pack.build_subset for an EXPLICIT block-id list.

    Mirrors build_subset's `sub` structure exactly (same keys, same build_shape +
    _common_masks construction) but the subset is `block_ids` (any blocks now
    assigned to `bay_id`) rather than the preferred-bay blocks build_subset picks.
    geom='poly' (real multi-layer polygons), identical to seed.make_seed's path.
    """
    bays, blocks = data["bays"], data["blocks"]
    subset = list(block_ids)
    W, H = bays[bay_id]["width"], bays[bay_id]["height"]
    meta, shapes, cm = {}, {}, {}
    max_layer = 1
    for i in subset:
        shs = [build_shape(i, blocks[i], o, scale)
               for o in range(len(blocks[i]["shape"]))]
        shapes[i] = shs
        for s in shs:
            cm[id(s)] = _common_masks(s, scale)
            max_layer = max(max_layer, s.n_layers)
        meta[i] = (blocks[i].get("release_time", 0),
                   blocks[i].get("processing_time", 0),
                   blocks[i].get("due_date", 0))
    return {"bay_id": bay_id, "W": W, "H": H, "max_layer": max_layer,
            "subset": subset, "meta": meta, "shapes": shapes, "cm": cm,
            "scale": scale, "raw": {i: blocks[i] for i in subset}}


# ---------------------------------------------------------------------------
def reassign_decode(data: dict, prob_path: str, time_s_pack: float = _PACK_TL,
                    polish: bool = False, scale: int = 2) -> dict:
    """Reassign (CP-SAT, z3-min) + re-decode each bay (crane-safe) + honest eval.

    Returns {prob, base_obj, base_z1, base_z2, base_z3, new_obj, new_z1, new_z3,
             accepted, polished_obj, polished_z1, polished_z3, status}.
    """
    prob_idx = int(os.path.basename(prob_path).split("_")[-1].split(".")[0])

    # --- (1) current solution -> base ------------------------------------
    sol = json.load(open(prob_path, encoding="utf-8"))
    cur = adapter.deserialize(data, sol, scale=scale)
    base = _seed.global_eval(data, cur)

    m = len(data["bays"])
    # --- (2) current per-bay counts + CP-SAT reassignment ----------------
    current_counts = [0] * m
    for j, placed in cur.items():
        if 0 <= j < m:
            current_counts[j] += len(placed)
    new_assign = _solve_assignment(data, current_counts, _ASSIGN_TL)
    if new_assign is None:
        return {"prob": prob_idx, "base_obj": base["obj"], "base_z1": base["z1"],
                "base_z2": base["z2"], "base_z3": base["z3"], "new_obj": None,
                "new_z1": None, "new_z3": None, "accepted": False,
                "polished_obj": None, "polished_z1": None, "polished_z3": None,
                "status": "ASSIGN_INFEASIBLE"}

    # --- (3) group ids by new bay; re-pack each bay from scratch ----------
    by_bay: dict[int, list] = {}
    for bid, j in new_assign.items():
        by_bay.setdefault(j, []).append(bid)

    new_bays_placed: dict[int, list] = {}
    for j, ids in by_bay.items():
        sub = _build_subset_ids(data, j, ids, scale)
        order = _tp.seed_order(sub, "edd")
        placed_j, _z1_j = _tp.simulate(sub, order, allow_stack=False, fit=True)
        new_bays_placed[j] = placed_j

    # --- (4) honest full-objective eval ----------------------------------
    ev = _seed.global_eval(data, new_bays_placed)

    # --- (5) NEVER-WORSE gate (report-only for a prototype) --------------
    accepted = bool(ev["feasible"] and ev["obj"] is not None
                    and base["obj"] is not None and ev["obj"] < base["obj"])

    # --- (6) optional polish: crane_repack_bay x/y passes to recover z1 --
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
                np_j, st, wall, cinfo = crane_cpsat.crane_repack_bay(
                    data, j, placed_j, min(_POLISH_BAY_TL, rem))
            except Exception:
                np_j = None
            polished[j] = np_j if np_j is not None else placed_j
        pev = _seed.global_eval(data, polished)
        polished_obj, polished_z1, polished_z3 = pev["obj"], pev["z1"], pev["z3"]

    return {
        "prob": prob_idx,
        "base_obj": base["obj"], "base_z1": base["z1"],
        "base_z2": base["z2"], "base_z3": base["z3"],
        "new_obj": ev["obj"], "new_z1": ev["z1"], "new_z3": ev["z3"],
        "new_feasible": ev["feasible"],
        "accepted": accepted,
        "polished_obj": polished_obj, "polished_z1": polished_z1,
        "polished_z3": polished_z3,
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

    print("=" * 132)
    print("REASSIGN PROTOTYPE -- cut z3 by bay reassignment (CP-SAT, count+15% cap), "
          "then re-pack each bay crane-safely, measure REAL full-obj.")
    print("  Key question: does the z3 gain SURVIVE the z1 re-packing cost?  "
          "(NEVER-WORSE gate: accept only if feasible AND new_obj < base_obj)")
    print("=" * 132)
    hdr = (f"{'prob':>4} | {'base_obj':>13} | {'new_obj(fresh)':>14} | "
           f"{'new_obj(polish)':>15} | {'z3 cur->new':>21} | "
           f"{'z1 cur->new':>21} | {'acc':>4}")
    print(hdr)
    print("-" * 132)

    rows = []
    for p in probs:
        inst = os.path.normpath(
            os.path.join(THIS, "..", "instances", "train", f"prob_{p}.json"))
        prob_path = os.path.join(THIS, f"real_prob_{p}.json")
        data = json.load(open(inst, encoding="utf-8"))
        t0 = time.monotonic()
        try:
            res = reassign_decode(data, prob_path, _PACK_TL, polish=polish)
        except Exception as e:
            print(f"{p:>4} | ERROR: {type(e).__name__}: {e}", flush=True)
            continue
        res["wall"] = time.monotonic() - t0
        rows.append(res)
        z3s = f"{_fmt(res['base_z3'])} -> {_fmt(res['new_z3'])}"
        z1s = f"{_fmt(res['base_z1'])} -> {_fmt(res['new_z1'])}"
        print(f"{res['prob']:>4} | {_fmt(res['base_obj']):>13} | "
              f"{_fmt(res['new_obj']):>14} | {_fmt(res['polished_obj']):>15} | "
              f"{z3s:>21} | {z1s:>21} | "
              f"{'YES' if res['accepted'] else 'no':>4}", flush=True)

    print("-" * 132)
    print("\nVERDICT (did cutting z3 survive the z1 re-packing cost?):")
    for res in rows:
        if res["new_obj"] is None or res["base_obj"] is None:
            why = ("reassignment INFEASIBLE to re-pack (oversized block -> bay it "
                   "doesn't fit; count cap is geometry-blind)"
                   if res.get("status") == "OK" and not res.get("new_feasible")
                   else res["status"])
            print(f"  prob_{res['prob']}: {why}  [{res.get('wall', 0):.1f}s]")
            continue
        dz3 = (res["base_z3"] - res["new_z3"]) if res["new_z3"] is not None else None
        dz1 = (res["new_z1"] - res["base_z1"]) if res["new_z1"] is not None else None
        dobj_fresh = res["new_obj"] - res["base_obj"]
        verdict = "NET IMPROVEMENT" if dobj_fresh < 0 else "z1 WIPED OUT z3 gain"
        pol = ""
        if res["polished_obj"] is not None:
            dobj_pol = res["polished_obj"] - res["base_obj"]
            pol = (f"  | polish dobj={dobj_pol:+,.0f} "
                   f"({'better' if dobj_pol < 0 else 'still worse'})")
        print(f"  prob_{res['prob']}: z3 down {_fmt(dz3)} (raw units), "
              f"z1 up {_fmt(dz1)} -> fresh dobj={dobj_fresh:+,.0f} "
              f"=> {verdict}{pol}  [{res['wall']:.1f}s]")
    print("=" * 132)


if __name__ == "__main__":
    main()
