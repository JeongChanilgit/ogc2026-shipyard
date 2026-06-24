"""
bpass.py -- cross-bay reassignment pass ("b-pass").

Move a tardy block that is in the WRONG bay to its PREFERRED bay, gated
never-worse on the FULL objective (official check_feasibility via
seed.global_eval).

Why this is safe / why it can help
----------------------------------
A block that is ALREADY tardy has its z1 penalty (exit - due) already incurred.
Moving it to a different bay barely changes z1 (it stays late -- it was already
late, and we let it enter as early as release allows in the new bay), but it can
CUT z3 (preference deviation) when the destination is the block's preferred bay.
So we target ONLY blocks that are BOTH tardy AND in the wrong bay, seed each into
its preferred bay, and let crane_cpsat re-pack JUST that block (free_ids={b}) so
every other block in the destination bay stays frozen (position + time constant).
Every accepted move passes the OFFICIAL full-solution checker on TOTAL obj, so
the pass is provably never-worse.

Move mechanic (the free_ids={b} trick)
---------------------------------------
We append a seed placement of b into bay k (start pose x=0,y=0 clamped, b's
current orient, entry=release, exit=entry+P) and call
`crane_repack_bay(data, k, placed_k + [b_seed], time_s, free_ids={b})`.  With
free_ids={b}, ONLY b gets candidate positions + a free entry IntVar; bay k's
existing blocks are FROZEN at their current pose+time.  CP-SAT thus finds a
crane-safe (x, y, entry) for b among bay k's fixed blocks (or places it late if
it must wait -- fine, it was already tardy).

Public API
----------
    bpass(data, bays_placed, total_time_s=120, n_xcand=5) -> (best_bays_placed, log)
    try_move(data, bays_placed, b_id, time_s, n_xcand=5) -> (trial_or_None, info)
    try_swap(data, bays_placed, b_id, time_s, n_xcand=5) -> (trial_or_None, info)

Swap mechanic (free_ids on BOTH bays)
-------------------------------------
try_swap exchanges a wrong-bay tardy block b (bay j, preferred k) with a partner
c chosen from bay k (preferring c whose preferred bay is j = mutual win, else any
other wrong-bay c, tie-broken by closest footprint area = load-preserving).  It
seeds c into bay j and b into bay k, then re-packs bay j with free_ids={c} and
bay k with free_ids={b} -- so each re-pack frees exactly the one incoming block
while every other block in that bay stays frozen.  The caller gates on the FULL
objective, so the swap is never-worse just like the move.
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

from gridmap import build_shape                       # noqa: E402
from shapely.affinity import translate as _translate  # noqa: E402
import crane_cpsat as _crane                          # noqa: E402
import xreopt_ref as _xref                            # noqa: E402
from seed import global_eval                          # noqa: E402


# ---------------------------------------------------------------------------
def _preferred(data, bid) -> int:
    """Preferred bay of block `bid` = argmax of its bay_preferences."""
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(range(len(prefs)), key=lambda j: prefs[j])


def _world(sh, x, y):
    """Per-layer polygons translated to (x, y) -- identical to adapter._world."""
    return {l: _translate(sh.layers[l].poly, xoff=x, yoff=y)
            for l in range(sh.n_layers)}


def _find_placed(bays_placed, b_id):
    """Return (bay_id, placed_record) for block b_id, or (None, None)."""
    for j, placed in bays_placed.items():
        for p in placed:
            if p["id"] == b_id:
                return j, p
    return None, None


def _seed_into_bay(data, k, pb):
    """Build a starting placed record for block pb["id"] in bay k.

    Start pose: x=0, y=0 clamped into bay k bounds for the SAME shape/orient as
    pb (it's the same block, same orientation -- only the bay frame changes), at
    entry = release_time, exit = entry + P (P = pb's observed processing span).
    """
    bid = pb["id"]
    orient = int(pb["orient"])
    sh = build_shape(bid, data["blocks"][bid], orient, scale=pb["sh"].scale)

    W = int(data["bays"][k]["width"])
    H = int(data["bays"][k]["height"])
    # clamp x=0 / y=0 into bay k's valid anchor range for this shape
    x = max(_xref._x_lb(sh), min(_xref._x_ub(sh, W), 0))
    y_lb = max(0, int(math.ceil(-sh.min_y - 1e-9)))
    y_ub = max(y_lb, int(math.floor(H - sh.max_y + 1e-9)))
    y = max(y_lb, min(y_ub, 0))

    R = int(data["blocks"][bid].get("release_time", 0))
    # processing span: prefer the observed exit-entry (matches the solver's P);
    # fall back to the instance processing_time.
    P = int(round(pb["exit"] - pb["entry"]))
    if P <= 0:
        P = int(data["blocks"][bid].get("processing_time", 0))
    entry = R
    exit_t = entry + P

    return {
        "id": bid,
        "sh": sh,
        "x": int(x),
        "y": int(y),
        "orient": orient,
        "entry": int(entry),
        "exit": int(exit_t),
        "world": _world(sh, int(x), int(y)),
    }


# ---------------------------------------------------------------------------
def try_move(data, bays_placed, b_id, time_s, n_xcand=5):
    """Attempt to move block b_id into its preferred bay.

    Returns (trial_bays_placed_or_None, info).  The CALLER applies the global_eval
    gate -- this function only constructs the trial layout (or None if no move is
    possible / the solver fails).
    """
    info = {"id": b_id, "from_bay": None, "to_bay": None, "reason": ""}

    j, pb = _find_placed(bays_placed, b_id)
    if pb is None:
        info["reason"] = "not-found"
        return None, info
    k = _preferred(data, b_id)
    info["from_bay"] = j
    info["to_bay"] = k
    if k == j:
        info["reason"] = "already-preferred"
        return None, info

    # 1) seed b into bay k at a clamped start pose
    b_seed = _seed_into_bay(data, k, pb)

    # 2) bay k = existing blocks (frozen) + seeded b (the only FREE block)
    placed_k_new = list(bays_placed.get(k, [])) + [b_seed]

    # 3) crane-aware re-pack: only b is free; bay k's blocks stay put
    new_k, status, wall, cinfo = _crane.crane_repack_bay(
        data, k, placed_k_new, time_s,
        n_xcand=n_xcand, n_ycand=0, n_ocand=0,
        free_ids={b_id})
    info["status"] = status
    info["cpsat_wall"] = wall
    if new_k is None:
        info["reason"] = f"solver-{status}"
        return None, info

    # 4) remove b from its source bay j
    new_j = [p for p in bays_placed[j] if p["id"] != b_id]

    # 5) assemble the trial layout (shallow-copy the dict; replace bays j and k)
    trial = dict(bays_placed)
    trial[j] = new_j
    trial[k] = new_k
    info["reason"] = "trial-built"
    return trial, info


# ---------------------------------------------------------------------------
def _footprint_area(pb) -> float:
    """Layer-0 footprint area of a placed record's shape (= floor occupancy)."""
    sh = pb["sh"]
    fa = getattr(sh, "footprint_area", None)
    if fa is not None:
        return float(fa)
    # fallback: bbox area
    return float((sh.max_x - sh.min_x) * (sh.max_y - sh.min_y))


def try_swap(data, bays_placed, b_id, time_s, n_xcand=5):
    """Attempt to SWAP block b_id (in bay j, preferred k) with a block c in bay k.

    Picks a partner c from bay k preferring, in order:
      1. c whose preferred bay == j  (mutual win: both blocks go home, z3 down),
      2. else c that is ALSO wrong-bay (moving c to j is at worst neutral on z3),
    and among the eligible c the one whose footprint area is closest to b's
    (load-preserving, keeps z2 imbalance from worsening).

    Build mechanic (mirrors try_move's free_ids={X} seed trick on BOTH bays):
      * bay j new list = (bay j minus b) + SEED(c into bay j frame), re-pack with
        free_ids={c}  (only c free, the rest of bay j frozen),
      * bay k new list = (bay k minus c) + SEED(b into bay k frame), re-pack with
        free_ids={b}  (only b free, the rest of bay k frozen).
    If either re-pack returns None, the swap fails (return None).

    Returns (trial_bays_placed_or_None, info).  Caller applies the global_eval gate.
    """
    info = {"id": b_id, "from_bay": None, "to_bay": None, "partner": None,
            "reason": "", "kind": "swap"}

    j, pb = _find_placed(bays_placed, b_id)
    if pb is None:
        info["reason"] = "not-found"
        return None, info
    k = _preferred(data, b_id)
    info["from_bay"] = j
    info["to_bay"] = k
    if k == j:
        info["reason"] = "already-preferred"
        return None, info

    placed_k = bays_placed.get(k, [])
    if not placed_k:
        info["reason"] = "empty-target-bay"
        return None, info

    b_area = _footprint_area(pb)

    # rank candidate partners c in bay k:
    #   tier 0 = c's preferred bay == j (mutual win)
    #   tier 1 = c is also wrong-bay (c's preferred != k) -> moving c to j neutral
    #   tier 2 = c is correctly placed in k (moving it to j HURTS c's z3) -> exclude
    # within an eligible tier, smaller |area(c) - area(b)| first (load-preserving).
    ranked = []
    for pc in placed_k:
        cid = pc["id"]
        if cid == b_id:
            continue
        pref_c = _preferred(data, cid)
        if pref_c == j:
            tier = 0
        elif pref_c != k:
            tier = 1
        else:
            continue                          # correctly-placed c: skip (tier 2)
        adiff = abs(_footprint_area(pc) - b_area)
        ranked.append((tier, adiff, cid, pc))

    if not ranked:
        info["reason"] = "no-eligible-partner"
        return None, info

    ranked.sort(key=lambda r: (r[0], r[1]))
    _, _, cid, pc = ranked[0]
    info["partner"] = cid

    # build the two seeded bay lists (mirror try_move's seed-into-bay)
    c_seed = _seed_into_bay(data, j, pc)      # c into bay j frame
    b_seed = _seed_into_bay(data, k, pb)      # b into bay k frame

    new_j_pre = [p for p in bays_placed[j] if p["id"] != b_id] + [c_seed]
    new_k_pre = [p for p in bays_placed.get(k, []) if p["id"] != cid] + [b_seed]

    # re-pack bay j with only c free; bay k with only b free
    new_j, st_j, wall_j, _cj = _crane.crane_repack_bay(
        data, j, new_j_pre, time_s,
        n_xcand=n_xcand, n_ycand=0, n_ocand=0, free_ids={cid})
    if new_j is None:
        info["reason"] = f"solver-j-{st_j}"
        info["status_j"] = st_j
        return None, info

    new_k, st_k, wall_k, _ck = _crane.crane_repack_bay(
        data, k, new_k_pre, time_s,
        n_xcand=n_xcand, n_ycand=0, n_ocand=0, free_ids={b_id})
    if new_k is None:
        info["reason"] = f"solver-k-{st_k}"
        info["status_k"] = st_k
        return None, info

    trial = dict(bays_placed)
    trial[j] = new_j
    trial[k] = new_k
    info["status_j"] = st_j
    info["status_k"] = st_k
    info["cpsat_wall"] = (wall_j or 0.0) + (wall_k or 0.0)
    info["reason"] = "trial-built"
    return trial, info


# ---------------------------------------------------------------------------
def _z3_contrib(data, bid, cur_bay):
    """Preference deviation (S_max - S_chosen) for block bid in cur_bay.

    Bigger = worse current bay -> more to gain by moving to preferred bay.
    """
    prefs = data["blocks"][bid]["bay_preferences"]
    return max(prefs) - prefs[cur_bay]


def bpass(data, bays_placed, total_time_s=120, n_xcand=5):
    """Cross-bay reassignment pass.  Provably never-worse on the FULL objective.

    Targets = blocks that are BOTH tardy (exit > due_date) AND in the wrong bay
    (current bay != preferred bay).  Each target is seeded into its preferred bay
    and re-packed with free_ids={b}; the move is accepted iff the OFFICIAL checker
    reports the trial feasible AND total obj strictly improves.

    Returns (best_bays_placed, log).
    """
    t_start = time.monotonic()
    cur = deepcopy(bays_placed)

    base = global_eval(data, cur)
    cur_obj = base["obj"]

    log = {
        "base": base,
        "n_targets": 0,
        "accepted": 0,
        "accepted_move": 0,
        "accepted_swap": 0,
        "rejected_infeasible": 0,
        "rejected_noimprove": 0,
        "no_move": 0,
        "moves": [],
    }

    # build target list: tardy AND wrong-bay
    targets = []
    for j, placed in cur.items():
        for p in placed:
            bid = p["id"]
            due = data["blocks"][bid].get("due_date", 0)
            if p["exit"] <= due:
                continue                       # not tardy -> skip
            k = _preferred(data, bid)
            if k == j:
                continue                       # already in preferred bay -> skip
            lateness = p["exit"] - due
            z3c = _z3_contrib(data, bid, j)
            targets.append((bid, z3c, lateness))

    # sort: biggest z3 contribution first, then biggest lateness
    targets.sort(key=lambda t: (t[1], t[2]), reverse=True)
    log["n_targets"] = len(targets)
    n_tgt = max(1, len(targets))

    deadline = t_start + total_time_s

    for bid, z3c, lateness in targets:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            log["moves"].append({"id": bid, "accepted": False,
                                 "reason": "deadline"})
            continue
        # per-move slice: spread the remaining budget across remaining targets
        per = max(8.0, remaining / n_tgt)
        per = min(per, remaining)

        # --- 1) try_move into preferred bay -------------------------------
        accepted_here = False
        trial, info = try_move(data, cur, bid, per, n_xcand=n_xcand)
        if trial is not None:
            ev = global_eval(data, trial)
            rec = {
                "id": bid, "kind": "move",
                "from_bay": info.get("from_bay"),
                "to_bay": info.get("to_bay"),
                "z3c": z3c,
                "obj_before": cur_obj,
                "obj_trial": ev["obj"],
                "feasible": ev["feasible"],
            }
            if (ev["feasible"] and ev["obj"] is not None
                    and ev["obj"] < cur_obj - 1e-6):
                prev_obj = cur_obj
                cur = trial
                cur_obj = ev["obj"]
                rec["accepted"] = True
                rec["obj_delta"] = ev["obj"] - prev_obj
                rec["reason"] = "accepted"
                log["accepted"] += 1
                log["accepted_move"] += 1
                accepted_here = True
            else:
                rec["accepted"] = False
                if not ev["feasible"]:
                    rec["reason"] = "infeasible"
                    log["rejected_infeasible"] += 1
                else:
                    rec["reason"] = "obj-not-improved"
                    log["rejected_noimprove"] += 1
            log["moves"].append(rec)
        else:
            log["no_move"] += 1
            log["moves"].append({"id": bid, "kind": "move", "accepted": False,
                                 "reason": info.get("reason", "no-move"),
                                 "from_bay": info.get("from_bay"),
                                 "to_bay": info.get("to_bay")})

        # --- 2) if the move didn't improve, try a SWAP --------------------
        if accepted_here:
            continue
        s_remaining = deadline - time.monotonic()
        if s_remaining <= 0.0:
            continue
        s_per = min(s_remaining, max(8.0, s_remaining / n_tgt))
        s_trial, s_info = try_swap(data, cur, bid, s_per, n_xcand=n_xcand)
        if s_trial is None:
            log["moves"].append({"id": bid, "kind": "swap", "accepted": False,
                                 "reason": s_info.get("reason", "no-swap"),
                                 "from_bay": s_info.get("from_bay"),
                                 "to_bay": s_info.get("to_bay"),
                                 "partner": s_info.get("partner")})
            continue
        ev = global_eval(data, s_trial)
        rec = {
            "id": bid, "kind": "swap",
            "from_bay": s_info.get("from_bay"),
            "to_bay": s_info.get("to_bay"),
            "partner": s_info.get("partner"),
            "z3c": z3c,
            "obj_before": cur_obj,
            "obj_trial": ev["obj"],
            "feasible": ev["feasible"],
        }
        if (ev["feasible"] and ev["obj"] is not None
                and ev["obj"] < cur_obj - 1e-6):
            prev_obj = cur_obj
            cur = s_trial
            cur_obj = ev["obj"]
            rec["accepted"] = True
            rec["obj_delta"] = ev["obj"] - prev_obj
            rec["reason"] = "accepted"
            log["accepted"] += 1
            log["accepted_swap"] += 1
        else:
            rec["accepted"] = False
            if not ev["feasible"]:
                rec["reason"] = "infeasible"
                log["rejected_infeasible"] += 1
            else:
                rec["reason"] = "obj-not-improved"
                log["rejected_noimprove"] += 1
        log["moves"].append(rec)

    final = global_eval(data, cur)
    log["final"] = final
    log["wall"] = time.monotonic() - t_start
    return cur, log


__all__ = ["bpass", "try_move", "try_swap", "_preferred"]
