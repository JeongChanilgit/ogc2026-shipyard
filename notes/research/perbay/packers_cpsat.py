"""Rolling-horizon (time-windowed) 4D CP-SAT per-bay packer (2026-06-18).

The whole-bay joint model (box-decomp) explodes for big bays (102 blocks here).
Idea (user 2026-06-18): SLICE — process blocks EDD-ordered in batches of K;
each batch is a SMALL box-decomp CP-SAT [(x,y,entry) joint, space-OR-time
disjunction], with all earlier batches FROZEN as fixed obstacles.  Model size
per solve = O(K^2 + K*relevant_frozen) instead of O(N^2) -> tractable.

v1: orientation FIXED per block (passed in, e.g. the baseline's choice) so we
isolate the (x,y,entry) joint-vs-greedy effect.  v2 will add orientation choice.

Crane-safe by the same invariant box-decomp uses: co-present blocks have
cell-disjoint footprints (>= K-rect cover pairwise-disjoint).
"""
from __future__ import annotations
import os, sys, time

ROOT = r"C:\claude-develop\OGC2026"
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
import boxsolver as bx     # _footprint_cells, _cell_rects (geometry)
import fastfloor as ff     # _fixed_time_decode (greedy floor)
from utils import Bay


def make_orders(ids, blocks):
    """Research-backed dispatching orders for the greedy decoder (per-bay w equal
    => w/p = 1/p).  EDD / release / slack / ATC / COVERT."""
    import math
    R = lambda b: blocks[b]["release_time"]
    P = lambda b: max(1, blocks[b]["processing_time"])
    D = lambda b: blocks[b]["due_date"]
    pbar = sum(P(b) for b in ids) / max(1, len(ids)); k = 2.0
    return {
        "EDD": sorted(ids, key=lambda b: (D(b), R(b))),
        "release": sorted(ids, key=lambda b: (R(b), D(b))),
        "slack": sorted(ids, key=lambda b: (D(b) - P(b) - R(b), D(b))),
        "ATC": sorted(ids, key=lambda b: -(1.0 / P(b)) * math.exp(-max(0, D(b) - P(b)) / (k * pbar))),
        "COVERT": sorted(ids, key=lambda b: -(1.0 / P(b)) * max(0.0, 1 - max(0, D(b) - P(b)) / (k * P(b)))),
    }


def solve_timing(prob, bay_id, placement, deadline, budget=8.0, workers=4):
    """Pure per-bay TIMING ORACLE (= what B3 does): positions (x,y,orient) FIXED,
    re-optimise entry times so footprint-cell-OVERLAPPING pairs are time-disjoint,
    minimise tardiness.  Exact 1-D disjunctive (cell overlap, not rect cover).
    Returns {b:(x,y,o,e,ex)} or None."""
    from ortools.sat.python import cp_model
    blocks = prob["blocks"]; ids = list(placement)
    wc = {}
    for b in ids:
        x, y, o = placement[b][0], placement[b][1], placement[b][2]
        cells = bx._footprint_cells(b, blocks[b], o)[0]
        wc[b] = frozenset((cx + x, cy + y) for (cx, cy) in cells)
    P = {b: int(blocks[b]["processing_time"]) for b in ids}
    overl = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))
             if wc[ids[i]] & wc[ids[j]]]
    Tub = max(int(blocks[b]["release_time"]) for b in ids) + sum(P.values())
    m = cp_model.CpModel(); ev = {}; tard = []
    for b in ids:
        R = int(blocks[b]["release_time"]); D = int(blocks[b]["due_date"])
        ev[b] = m.NewIntVar(R, Tub, ""); td = m.NewIntVar(0, Tub + P[b], "")
        m.Add(td >= ev[b] + P[b] - D); tard.append(td)
        m.AddHint(ev[b], int(placement[b][3]))
    for a, c in overl:
        ab = m.NewBoolVar("")
        m.Add(ev[a] + P[a] <= ev[c]).OnlyEnforceIf(ab)
        m.Add(ev[c] + P[c] <= ev[a]).OnlyEnforceIf(ab.Not())
    m.Minimize(sum(tard))
    s = cp_model.CpSolver(); s.parameters.max_time_in_seconds = max(0.5, float(budget))
    s.parameters.num_search_workers = int(workers); s.parameters.random_seed = 1
    if s.Solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return {b: (placement[b][0], placement[b][1], placement[b][2],
                int(s.Value(ev[b])), int(s.Value(ev[b])) + P[b]) for b in ids}


def pack_order_race(prob, bay_id, ids, deadline, timing=True, timing_budget=8.0):
    """Greedy floor over multiple research-backed ORDERS, keep best, then apply the
    timing oracle.  Returns ({b:(x,y,o,e,ex)}, z1, best_order_name)."""
    import time as _t
    blocks = prob["blocks"]; bay = Bay.from_dict(prob["bays"][bay_id], bay_id)
    best = None; best_z1 = float("inf"); best_nm = None
    for nm, order in make_orders(ids, blocks).items():
        if _t.monotonic() >= deadline - (timing_budget if timing else 0) - 0.5:
            break
        asgn, _ft = ff._fixed_time_decode(bay, bay_id, ids, blocks,
                                          _t.monotonic() + 25, order_key=list(order))
        if asgn is None:
            continue
        z1 = sum(max(0, asgn[b]["exit_time"] - blocks[b]["due_date"]) for b in ids)
        if z1 < best_z1:
            best_z1 = z1; best_nm = nm
            best = {b: (asgn[b]["x"], asgn[b]["y"], asgn[b]["orient_idx"],
                        asgn[b]["entry_time"], asgn[b]["exit_time"]) for b in ids}
    if best is None:
        return None, float("inf"), None
    if timing:
        t = solve_timing(prob, bay_id, best, deadline, timing_budget)
        if t is not None:
            tz = sum(max(0, t[b][4] - blocks[b]["due_date"]) for b in ids)
            if tz < best_z1:
                best, best_z1 = t, tz
    return best, best_z1, best_nm


def pack_windowed_cpsat(prob, bay_id, ids, deadline, orient_of,
                        K=8, batch_s=3.0, workers=4, krect=2):
    from ortools.sat.python import cp_model
    blocks = prob["blocks"]
    bd = prob["bays"][bay_id]
    W = int(bd["width"]); H = int(bd["height"])

    geo = {}
    for b in ids:
        o = int(orient_of[b])
        cells, cb = bx._footprint_cells(b, blocks[b], o)
        if not cells:
            return None
        rects = bx._cell_rects(cells, cb, krect)
        geo[b] = {"o": o, "cb": cb, "rects": rects,
                  "R": int(blocks[b]["release_time"]),
                  "P": int(blocks[b]["processing_time"]),
                  "D": int(blocks[b]["due_date"])}
    order = sorted(ids, key=lambda b: (geo[b]["D"], geo[b]["R"]))
    Tub = max(g["R"] for g in geo.values()) + sum(g["P"] for g in geo.values())

    frozen = []          # {entry, exit, wrects:[(x0,y0,x1,y1)...]}
    placement = {}
    i = 0
    while i < len(order):
        if time.monotonic() >= deadline - 0.5:
            return None
        batch = order[i:i + K]; i += K
        mdl = cp_model.CpModel()
        tx = {}; ty = {}; ev = {}; tard = []
        for b in batch:
            g = geo[b]; cb = g["cb"]
            txlo = -cb[0]; txhi = (W - 1) - cb[2]
            tylo = -cb[1]; tyhi = (H - 1) - cb[3]
            if txhi < txlo or tyhi < tylo:
                return None
            tx[b] = mdl.NewIntVar(txlo, txhi, "")
            ty[b] = mdl.NewIntVar(tylo, tyhi, "")
            ev[b] = mdl.NewIntVar(g["R"], Tub, "")
            td = mdl.NewIntVar(0, Tub + g["P"], "")
            mdl.Add(td >= ev[b] + g["P"] - g["D"])
            tard.append(td)
        # within-batch pairwise: space-disjoint OR time-disjoint
        for ii in range(len(batch)):
            a = batch[ii]; Pa = geo[a]["P"]
            for kk in range(ii + 1, len(batch)):
                c = batch[kk]; Pc = geo[c]["P"]
                aT = mdl.NewBoolVar(""); cT = mdl.NewBoolVar("")
                mdl.Add(ev[a] - ev[c] <= -Pa).OnlyEnforceIf(aT)   # a fully before c
                mdl.Add(ev[c] - ev[a] <= -Pc).OnlyEnforceIf(cT)
                for (rax0, ray0, rax1, ray1) in geo[a]["rects"]:
                    for (rcx0, rcy0, rcx1, rcy1) in geo[c]["rects"]:
                        aL = mdl.NewBoolVar(""); cL = mdl.NewBoolVar("")
                        aD = mdl.NewBoolVar(""); cD = mdl.NewBoolVar("")
                        mdl.Add(tx[a] - tx[c] <= rcx0 - rax1 - 1).OnlyEnforceIf(aL)
                        mdl.Add(tx[c] - tx[a] <= rax0 - rcx1 - 1).OnlyEnforceIf(cL)
                        mdl.Add(ty[a] - ty[c] <= rcy0 - ray1 - 1).OnlyEnforceIf(aD)
                        mdl.Add(ty[c] - ty[a] <= ray0 - rcy1 - 1).OnlyEnforceIf(cD)
                        mdl.AddBoolOr([aL, cL, aD, cD, aT, cT])
        # vs frozen obstacles (fixed positions); prune temporally-impossible pairs
        for b in batch:
            g = geo[b]
            for f in frozen:
                if f["exit"] <= g["R"]:
                    continue                 # frozen gone before b can release -> never co-present
                bBeforeF = mdl.NewBoolVar(""); fBeforeB = mdl.NewBoolVar("")
                mdl.Add(ev[b] + g["P"] <= f["entry"]).OnlyEnforceIf(bBeforeF)
                mdl.Add(f["exit"] <= ev[b]).OnlyEnforceIf(fBeforeB)
                for (rbx0, rby0, rbx1, rby1) in g["rects"]:
                    for (fx0, fy0, fx1, fy1) in f["wrects"]:
                        L = mdl.NewBoolVar(""); Rr = mdl.NewBoolVar("")
                        Dn = mdl.NewBoolVar(""); Up = mdl.NewBoolVar("")
                        mdl.Add(tx[b] <= fx0 - rbx1 - 1).OnlyEnforceIf(L)   # b left of f
                        mdl.Add(tx[b] >= fx1 - rbx0 + 1).OnlyEnforceIf(Rr)  # b right of f
                        mdl.Add(ty[b] <= fy0 - rby1 - 1).OnlyEnforceIf(Dn)
                        mdl.Add(ty[b] >= fy1 - rby0 + 1).OnlyEnforceIf(Up)
                        mdl.AddBoolOr([L, Rr, Dn, Up, bBeforeF, fBeforeB])
        mdl.Minimize(sum(tard))
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = max(0.5, min(float(batch_s),
                                                        deadline - time.monotonic() - 0.5))
        s.parameters.num_search_workers = int(workers)
        s.parameters.random_seed = 1
        if s.Solve(mdl) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        for b in batch:
            x = int(s.Value(tx[b])); y = int(s.Value(ty[b])); e = int(s.Value(ev[b]))
            g = geo[b]
            placement[b] = (x, y, g["o"], e, e + g["P"])
            frozen.append({"entry": e, "exit": e + g["P"],
                           "wrects": [(x + r[0], y + r[1], x + r[2], y + r[3])
                                      for r in g["rects"]]})
    return placement


# ===========================================================================
# ALNS: start from a solution, repeatedly DESTROY a subset of blocks and REPAIR
# them jointly with CP-SAT (the rest frozen as obstacles).  Greedy acceptance ⇒
# total z1 monotonically decreases ⇒ never worse than the init (e.g. baseline).
# Destroy operators include the user's "swap blocks between adjacent windows".
# ===========================================================================
def _build_geo(prob, bay_id, ids, orient_of, krect=2):
    blocks = prob["blocks"]; bd = prob["bays"][bay_id]
    W = int(bd["width"]); H = int(bd["height"])
    geo = {}
    for b in ids:
        o = int(orient_of[b])
        cells, cb = bx._footprint_cells(b, blocks[b], o)
        if not cells:
            return None, W, H
        geo[b] = {"o": o, "cb": cb, "rects": bx._cell_rects(cells, cb, krect),
                  "R": int(blocks[b]["release_time"]),
                  "P": int(blocks[b]["processing_time"]),
                  "D": int(blocks[b]["due_date"])}
    return geo, W, H


def _world_rects(pb, geo_b):
    x, y = pb[0], pb[1]
    rects = geo_b["orients"][pb[2]][1] if "orients" in geo_b else geo_b["rects"]
    return [(x + r[0], y + r[1], x + r[2], y + r[3]) for r in rects]


def _geo4(prob, bay_id, ids, force_orient, ncand=2, krect=2):
    """Geo with up to `ncand` candidate orientations per block (smallest-footprint
    first, ALWAYS including the current/forced orientation) for 4D repair."""
    blocks = prob["blocks"]; bd = prob["bays"][bay_id]
    W = int(bd["width"]); H = int(bd["height"])
    geo = {}
    for b in ids:
        nor = len(blocks[b].get("shape", []) or [1]) or 1
        scored = []
        for o in range(max(1, nor)):
            cells, cb = bx._footprint_cells(b, blocks[b], o)
            if cells:
                scored.append((len(cells), o, cb, bx._cell_rects(cells, cb, krect)))
        if not scored:
            return None, W, H
        scored.sort(key=lambda t: t[0])
        chosen = {}
        fo = int(force_orient[b])
        for (_, o, cb, rects) in scored:
            if o == fo:
                chosen[o] = (cb, rects)
        for (_, o, cb, rects) in scored:
            if len(chosen) >= ncand:
                break
            chosen.setdefault(o, (cb, rects))
        geo[b] = {"R": int(blocks[b]["release_time"]),
                  "P": int(blocks[b]["processing_time"]),
                  "D": int(blocks[b]["due_date"]),
                  "orients": chosen, "ocands": list(chosen.keys())}
    return geo, W, H


def solve_subset_4d(subset, geo, W, H, Tub, frozen, budget, workers=4, seed=1,
                    hint=None):
    """Like solve_subset but also CHOOSES orientation per block (4D: x,y,orient,
    entry).  Disjunctions are made conditional on the orientation selectors via
    extra Not() literals in each clause."""
    from ortools.sat.python import cp_model
    mdl = cp_model.CpModel()
    tx = {}; ty = {}; ev = {}; tard = []; sel = {}
    for b in subset:
        g = geo[b]
        lows_x = []; his_x = []; lows_y = []; his_y = []
        for o in g["ocands"]:
            cb = g["orients"][o][0]
            lows_x.append(-cb[0]); his_x.append((W - 1) - cb[2])
            lows_y.append(-cb[1]); his_y.append((H - 1) - cb[3])
        tx[b] = mdl.NewIntVar(min(lows_x), max(his_x), "")
        ty[b] = mdl.NewIntVar(min(lows_y), max(his_y), "")
        ev[b] = mdl.NewIntVar(g["R"], Tub, "")
        td = mdl.NewIntVar(0, Tub + g["P"], ""); mdl.Add(td >= ev[b] + g["P"] - g["D"])
        tard.append(td)
        sel[b] = {}
        for o in g["ocands"]:
            sv = mdl.NewBoolVar(""); sel[b][o] = sv
            cb = g["orients"][o][0]
            mdl.Add(tx[b] >= -cb[0]).OnlyEnforceIf(sv)
            mdl.Add(tx[b] <= (W - 1) - cb[2]).OnlyEnforceIf(sv)
            mdl.Add(ty[b] >= -cb[1]).OnlyEnforceIf(sv)
            mdl.Add(ty[b] <= (H - 1) - cb[3]).OnlyEnforceIf(sv)
        mdl.AddExactlyOne(list(sel[b].values()))
    for ii in range(len(subset)):
        a = subset[ii]; Pa = geo[a]["P"]
        for kk in range(ii + 1, len(subset)):
            c = subset[kk]; Pc = geo[c]["P"]
            aT = mdl.NewBoolVar(""); cT = mdl.NewBoolVar("")
            mdl.Add(ev[a] - ev[c] <= -Pa).OnlyEnforceIf(aT)
            mdl.Add(ev[c] - ev[a] <= -Pc).OnlyEnforceIf(cT)
            for oa in geo[a]["ocands"]:
                for oc in geo[c]["ocands"]:
                    na = sel[a][oa].Not(); nc = sel[c][oc].Not()
                    for (rax0, ray0, rax1, ray1) in geo[a]["orients"][oa][1]:
                        for (rcx0, rcy0, rcx1, rcy1) in geo[c]["orients"][oc][1]:
                            aL = mdl.NewBoolVar(""); cL = mdl.NewBoolVar("")
                            aD = mdl.NewBoolVar(""); cD = mdl.NewBoolVar("")
                            mdl.Add(tx[a] - tx[c] <= rcx0 - rax1 - 1).OnlyEnforceIf(aL)
                            mdl.Add(tx[c] - tx[a] <= rax0 - rcx1 - 1).OnlyEnforceIf(cL)
                            mdl.Add(ty[a] - ty[c] <= rcy0 - ray1 - 1).OnlyEnforceIf(aD)
                            mdl.Add(ty[c] - ty[a] <= ray0 - rcy1 - 1).OnlyEnforceIf(cD)
                            mdl.AddBoolOr([aL, cL, aD, cD, aT, cT, na, nc])
    for b in subset:
        g = geo[b]
        for f in frozen:
            if f["exit"] <= g["R"]:
                continue
            bBeforeF = mdl.NewBoolVar(""); fBeforeB = mdl.NewBoolVar("")
            mdl.Add(ev[b] + g["P"] <= f["entry"]).OnlyEnforceIf(bBeforeF)
            mdl.Add(f["exit"] <= ev[b]).OnlyEnforceIf(fBeforeB)
            for o in g["ocands"]:
                no = sel[b][o].Not()
                for (rbx0, rby0, rbx1, rby1) in g["orients"][o][1]:
                    for (fx0, fy0, fx1, fy1) in f["wrects"]:
                        L = mdl.NewBoolVar(""); Rr = mdl.NewBoolVar("")
                        Dn = mdl.NewBoolVar(""); Up = mdl.NewBoolVar("")
                        mdl.Add(tx[b] <= fx0 - rbx1 - 1).OnlyEnforceIf(L)
                        mdl.Add(tx[b] >= fx1 - rbx0 + 1).OnlyEnforceIf(Rr)
                        mdl.Add(ty[b] <= fy0 - rby1 - 1).OnlyEnforceIf(Dn)
                        mdl.Add(ty[b] >= fy1 - rby0 + 1).OnlyEnforceIf(Up)
                        mdl.AddBoolOr([L, Rr, Dn, Up, bBeforeF, fBeforeB, no])
    if hint:
        for b in subset:
            if b in hint and hint[b][2] in sel[b]:
                mdl.AddHint(sel[b][hint[b][2]], 1)
                mdl.AddHint(tx[b], hint[b][0]); mdl.AddHint(ty[b], hint[b][1])
                mdl.AddHint(ev[b], hint[b][3])
    mdl.Minimize(sum(tard))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = max(0.3, float(budget))
    s.parameters.num_search_workers = int(workers); s.parameters.random_seed = int(seed)
    if s.Solve(mdl) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    out = {}
    for b in subset:
        cho = next(o for o in geo[b]["ocands"] if s.Value(sel[b][o]) == 1)
        x = int(s.Value(tx[b])); y = int(s.Value(ty[b])); e = int(s.Value(ev[b]))
        out[b] = (x, y, cho, e, e + geo[b]["P"])
    return out


def solve_subset(subset, geo, W, H, Tub, frozen, budget, workers=4, seed=1,
                 hint=None):
    from ortools.sat.python import cp_model
    mdl = cp_model.CpModel()
    tx = {}; ty = {}; ev = {}; tard = []
    for b in subset:
        g = geo[b]; cb = g["cb"]
        txlo = -cb[0]; txhi = (W - 1) - cb[2]
        tylo = -cb[1]; tyhi = (H - 1) - cb[3]
        if txhi < txlo or tyhi < tylo:
            return None
        tx[b] = mdl.NewIntVar(txlo, txhi, ""); ty[b] = mdl.NewIntVar(tylo, tyhi, "")
        ev[b] = mdl.NewIntVar(g["R"], Tub, "")
        td = mdl.NewIntVar(0, Tub + g["P"], ""); mdl.Add(td >= ev[b] + g["P"] - g["D"])
        tard.append(td)
    for ii in range(len(subset)):
        a = subset[ii]; Pa = geo[a]["P"]
        for kk in range(ii + 1, len(subset)):
            c = subset[kk]; Pc = geo[c]["P"]
            aT = mdl.NewBoolVar(""); cT = mdl.NewBoolVar("")
            mdl.Add(ev[a] - ev[c] <= -Pa).OnlyEnforceIf(aT)
            mdl.Add(ev[c] - ev[a] <= -Pc).OnlyEnforceIf(cT)
            for (rax0, ray0, rax1, ray1) in geo[a]["rects"]:
                for (rcx0, rcy0, rcx1, rcy1) in geo[c]["rects"]:
                    aL = mdl.NewBoolVar(""); cL = mdl.NewBoolVar("")
                    aD = mdl.NewBoolVar(""); cD = mdl.NewBoolVar("")
                    mdl.Add(tx[a] - tx[c] <= rcx0 - rax1 - 1).OnlyEnforceIf(aL)
                    mdl.Add(tx[c] - tx[a] <= rax0 - rcx1 - 1).OnlyEnforceIf(cL)
                    mdl.Add(ty[a] - ty[c] <= rcy0 - ray1 - 1).OnlyEnforceIf(aD)
                    mdl.Add(ty[c] - ty[a] <= ray0 - rcy1 - 1).OnlyEnforceIf(cD)
                    mdl.AddBoolOr([aL, cL, aD, cD, aT, cT])
    for b in subset:
        g = geo[b]
        for f in frozen:
            if f["exit"] <= g["R"]:
                continue
            bBeforeF = mdl.NewBoolVar(""); fBeforeB = mdl.NewBoolVar("")
            mdl.Add(ev[b] + g["P"] <= f["entry"]).OnlyEnforceIf(bBeforeF)
            mdl.Add(f["exit"] <= ev[b]).OnlyEnforceIf(fBeforeB)
            for (rbx0, rby0, rbx1, rby1) in g["rects"]:
                for (fx0, fy0, fx1, fy1) in f["wrects"]:
                    L = mdl.NewBoolVar(""); Rr = mdl.NewBoolVar("")
                    Dn = mdl.NewBoolVar(""); Up = mdl.NewBoolVar("")
                    mdl.Add(tx[b] <= fx0 - rbx1 - 1).OnlyEnforceIf(L)
                    mdl.Add(tx[b] >= fx1 - rbx0 + 1).OnlyEnforceIf(Rr)
                    mdl.Add(ty[b] <= fy0 - rby1 - 1).OnlyEnforceIf(Dn)
                    mdl.Add(ty[b] >= fy1 - rby0 + 1).OnlyEnforceIf(Up)
                    mdl.AddBoolOr([L, Rr, Dn, Up, bBeforeF, fBeforeB])
    if hint:
        for b in subset:
            if b in hint:
                mdl.AddHint(tx[b], hint[b][0]); mdl.AddHint(ty[b], hint[b][1])
                mdl.AddHint(ev[b], hint[b][3])
    mdl.Minimize(sum(tard))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = max(0.3, float(budget))
    s.parameters.num_search_workers = int(workers); s.parameters.random_seed = int(seed)
    if s.Solve(mdl) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return {b: (int(s.Value(tx[b])), int(s.Value(ty[b])), geo[b]["o"],
                int(s.Value(ev[b])), int(s.Value(ev[b])) + geo[b]["P"]) for b in subset}


def perbay_lb(prob, bay_id, ids, budget=20.0, workers=4):
    """Lower bound on per-bay z1: area-time cumulative relaxation (co-present
    footprint-area sum <= bay area is NECESSARY for crane-safe packing).  Demand =
    SMALLEST-orientation footprint cells (loosest => valid LB).  Returns
    (proven_LB, best_found)."""
    from ortools.sat.python import cp_model
    blocks = prob["blocks"]; bd = prob["bays"][bay_id]
    cap = max(1, int(bd["width"]) * int(bd["height"]))
    m = cp_model.CpModel()
    Tub = max(int(blocks[b]["release_time"]) for b in ids) + \
        sum(int(blocks[b]["processing_time"]) for b in ids)
    ivs = []; dems = []; tard = []
    for b in ids:
        R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
        D = int(blocks[b]["due_date"])
        nor = len(blocks[b].get("shape", []) or [1])
        amin = cap
        for o in range(max(1, nor)):
            try:
                cells, _ = bx._footprint_cells(b, blocks[b], o)
                if cells:
                    amin = min(amin, len(cells))
            except Exception:
                pass
        e = m.NewIntVar(R, Tub, ""); iv = m.NewIntervalVar(e, P, e + P, "")
        ivs.append(iv); dems.append(max(1, min(amin, cap)))
        td = m.NewIntVar(0, Tub + P, ""); m.Add(td >= e + P - D); tard.append(td)
    m.AddCumulative(ivs, dems, cap)
    m.Minimize(sum(tard))
    s = cp_model.CpSolver(); s.parameters.max_time_in_seconds = float(budget)
    s.parameters.num_search_workers = int(workers)
    s.Solve(m)
    return s.BestObjectiveBound(), s.ObjectiveValue()


def pack_alns(prob, bay_id, ids, deadline, init_placement, orient_of,
              subset=12, nwin=8, workers=4, seed=1, repair_s=2.0,
              sa=False, T0=20.0, use_4d=False, ncand=2):
    import random, math, time as _t
    rng = random.Random(seed)
    if use_4d:
        geo, W, H = _geo4(prob, bay_id, ids, orient_of, ncand)
    else:
        geo, W, H = _build_geo(prob, bay_id, ids, orient_of)
    if geo is None:
        return None, (0, 0)
    _solve = solve_subset_4d if use_4d else solve_subset
    Tub = max(g["R"] for g in geo.values()) + sum(g["P"] for g in geo.values())
    place = {b: tuple(init_placement[b]) for b in ids}
    emin = min(place[b][3] for b in ids); emax = max(place[b][4] for b in ids)
    wspan = max(1, (emax - emin) // nwin)

    def win_of(b):
        return min(nwin - 1, (place[b][3] - emin) // wspan)

    def op_tardy(k):
        t = [b for b in ids if place[b][4] > geo[b]["D"]]
        rng.shuffle(t)
        t.sort(key=lambda b: place[b][4] - geo[b]["D"], reverse=True)
        return t[:k]

    def op_window(k):
        w = rng.randrange(nwin); pool = [b for b in ids if win_of(b) == w]
        rng.shuffle(pool); return pool[:k]

    def op_adjacent(k):                 # user's idea: swap across adjacent windows
        w = rng.randrange(max(1, nwin - 1))
        pool = [b for b in ids if win_of(b) in (w, w + 1)]
        rng.shuffle(pool); return pool[:k]

    def op_random(k):
        return rng.sample(ids, min(k, len(ids)))

    ops = [("tardy", op_tardy), ("window", op_window),
           ("adjacent", op_adjacent), ("random", op_random)]
    wts = [1.0] * len(ops); iters = 0; acc = 0

    def total_z1(pl):
        return sum(max(0, pl[b][4] - geo[b]["D"]) for b in ids)

    cur_z1 = total_z1(place)
    best = dict(place); best_z1 = cur_z1
    t_start = _t.monotonic()
    while _t.monotonic() < deadline - repair_s:
        tot = sum(wts); r = rng.random() * tot; cum = 0.0; ci = 0
        for idx, wv in enumerate(wts):
            cum += wv
            if r <= cum:
                ci = idx; break
        S = ops[ci][1](subset)
        if len(S) < 2:
            continue
        Sset = set(S)
        frozen = [{"entry": place[b][3], "exit": place[b][4],
                   "wrects": _world_rects(place[b], geo[b])}
                  for b in ids if b not in Sset]
        old = sum(max(0, place[b][4] - geo[b]["D"]) for b in S)
        sub = _solve(S, geo, W, H, Tub, frozen, repair_s, workers, seed,
                     hint={b: place[b] for b in S})
        iters += 1
        if sub is None:
            wts[ci] = max(0.1, wts[ci] * 0.95); continue
        new = sum(max(0, sub[b][4] - geo[b]["D"]) for b in S)
        delta = new - old
        accept = delta < -1e-9
        if not accept and sa:                       # SA: sometimes accept worse
            frac = max(0.0, (deadline - _t.monotonic()) / max(1e-9, deadline - t_start))
            T = max(1.0, T0 * frac)
            try:
                accept = rng.random() < math.exp(-delta / T)
            except OverflowError:
                accept = False
        if accept:
            for b in S:
                place[b] = sub[b]
            cur_z1 += delta; acc += 1
            wts[ci] = wts[ci] + 1.0 if delta < 0 else max(0.1, wts[ci])
            if cur_z1 < best_z1:
                best_z1 = cur_z1; best = dict(place)
        else:
            wts[ci] = max(0.1, wts[ci] * 0.98)
    return best, (iters, acc)


def pack_rand_multistart(prob, bay_id, ids, time_budget, n_starts=40, seed=1,
                         n_tjit=3, timing=True):
    """User idea (2026-06-18): break the rigid entry=R-first decode. Each block is
    placed at a RANDOM NON-TARDY entry t in [R, D-P] (using slack to spread peak
    co-presence), at a BL cell-disjoint position; placement ORDER is semi-random
    (EDD+noise / full-random); MULTI-START keep-best-z1; then B3 timing polish on
    the best layout.  Returns {b:(x,y,o,e,ex)} or None."""
    import random, time as _t
    deadline = _t.monotonic() + float(time_budget)
    blocks = prob["blocks"]; bd = prob["bays"][bay_id]
    W = int(bd["width"]); H = int(bd["height"])
    geo = {}
    for b in ids:
        nor = len(blocks[b].get("shape", []) or [1]) or 1
        best = None
        for o in range(max(1, nor)):
            cells, cb = bx._footprint_cells(b, blocks[b], o)
            if cells and (best is None or len(cells) < best[0]):
                best = (len(cells), o, cb)
        if best is None:
            return None
        geo[b] = {"o": best[1], "cb": best[2], "R": int(blocks[b]["release_time"]),
                  "P": int(blocks[b]["processing_time"]), "D": int(blocks[b]["due_date"])}

    def _fit(b, o, copres, t):
        return bx._bl_fit_cells(b, blocks[b], o, copres, W, H)

    best_place = None; best_z1 = float("inf"); s = 0
    while _t.monotonic() < deadline - 1.0 and s < n_starts:
        rng = random.Random(seed * 1000 + s); s += 1
        order = list(ids)
        if s == 1:
            order.sort(key=lambda b: (geo[b]["D"], geo[b]["R"]))     # start1 = EDD
        elif rng.random() < 0.5:
            order.sort(key=lambda b: (geo[b]["D"], rng.random()))    # EDD + noise
        else:
            rng.shuffle(order)                                        # full random
        placed = []; result = {}; ok = True
        for b in order:
            g = geo[b]; R, P, D = g["R"], g["P"], g["D"]
            hi = max(R, D - P)
            ts = [R] + ([rng.randint(R, hi) for _ in range(n_tjit)] if hi > R else [])
            pb = None
            for t in ts:                                  # try non-tardy times
                e = t + P
                cop = [(pl["c"], pl["cb"]) for pl in placed if pl["a"] < e and pl["e"] > t]
                fit = _fit(b, g["o"], cop, t)
                if fit:
                    pb = (fit[0], fit[1], t, e, fit[2], fit[3]); break
            if pb is None:                                # delay to a freeing exit
                for t in sorted({pl["e"] for pl in placed if pl["e"] > R}):
                    e = t + P
                    cop = [(pl["c"], pl["cb"]) for pl in placed if pl["a"] < e and pl["e"] > t]
                    fit = _fit(b, g["o"], cop, t)
                    if fit:
                        pb = (fit[0], fit[1], t, e, fit[2], fit[3]); break
            if pb is None:                                # forced empty window
                t = max([R] + [pl["e"] for pl in placed]); e = t + P
                fit = _fit(b, g["o"], [], t)
                if fit is None:
                    ok = False; break
                pb = (fit[0], fit[1], t, e, fit[2], fit[3])
            placed.append({"c": pb[4], "cb": pb[5], "a": pb[2], "e": pb[3]})
            result[b] = (pb[0], pb[1], g["o"], pb[2], pb[3])
        if not ok:
            continue
        z1 = sum(max(0, result[b][4] - geo[b]["D"]) for b in ids)
        if z1 < best_z1:
            best_z1 = z1; best_place = result
    if best_place is None:
        return None
    if timing and _t.monotonic() < deadline - 1.0:
        tt = solve_timing(prob, bay_id, best_place, deadline,
                          min(8.0, deadline - _t.monotonic()))
        if tt is not None and sum(max(0, tt[b][4] - geo[b]["D"]) for b in ids) < best_z1:
            best_place = tt
    return best_place


def pack_schedule_first(prob, bay_id, ids, time_budget, rho=0.95, b3=False, workers=4):
    """User Option-2 (2026-06-18): SCHEDULE FIRST, then position. Philosophically
    time->position (the correct order), vs B2/B3's position->time.
    Step 1: CP-SAT min-tardiness s.t. cumulative footprint-AREA <= bay*rho (the
            'minimise peak simultaneous occupied area' schedule).
    Step 2: place positions at those scheduled entry times (BL cell-disjoint among
            co-present); on geometric fail, slide to the next freeing time.
    b3=True re-times optimally afterwards (hybrid); b3=False keeps the schedule."""
    from ortools.sat.python import cp_model
    import time as _t
    deadline = _t.monotonic() + float(time_budget)
    blocks = prob["blocks"]; bd = prob["bays"][bay_id]
    W = int(bd["width"]); H = int(bd["height"]); cap = max(1, int(W * H * rho))
    geo = {}
    for b in ids:
        nor = len(blocks[b].get("shape", []) or [1]) or 1
        best = None
        for o in range(max(1, nor)):
            cells, cb = bx._footprint_cells(b, blocks[b], o)
            if cells and (cb[2] - cb[0] + 1) <= W and (cb[3] - cb[1] + 1) <= H:
                if best is None or len(cells) < best[0]:
                    best = (len(cells), o, cb)
        if best is None:
            return None
        geo[b] = {"area": best[0], "o": best[1], "cb": best[2],
                  "R": int(blocks[b]["release_time"]),
                  "P": int(blocks[b]["processing_time"]),
                  "D": int(blocks[b]["due_date"])}
    # --- Step 1: area-cumulative min-tardiness SCHEDULE ---
    m = cp_model.CpModel()
    Tub = max(g["R"] for g in geo.values()) + sum(g["P"] for g in geo.values())
    ev = {}; tard = []; ivs = []; dems = []
    for b in ids:
        g = geo[b]
        ev[b] = m.NewIntVar(g["R"], Tub, "")
        td = m.NewIntVar(0, Tub + g["P"], ""); m.Add(td >= ev[b] + g["P"] - g["D"])
        tard.append(td)
        ivs.append(m.NewIntervalVar(ev[b], g["P"], ev[b] + g["P"], ""))
        dems.append(min(g["area"], cap))
    m.AddCumulative(ivs, dems, cap)
    m.Minimize(sum(tard))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = max(1.0, min(0.55 * time_budget,
                                                    deadline - _t.monotonic() - 3.0))
    s.parameters.num_search_workers = workers; s.parameters.random_seed = 1
    if s.Solve(m) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    sched = {b: int(s.Value(ev[b])) for b in ids}
    # --- Step 2: position at scheduled times (BL), slide on geometric fail ---
    order = sorted(ids, key=lambda b: (sched[b], geo[b]["D"]))
    placed = []; result = {}
    for b in order:
        g = geo[b]; t = sched[b]; P = g["P"]
        ok = False
        for _ in range(60):
            e = t + P
            cop = [(pl["c"], pl["cb"]) for pl in placed if pl["a"] < e and pl["e"] > t]
            fit = bx._bl_fit_cells(b, blocks[b], g["o"], cop, W, H)
            if fit:
                placed.append({"c": fit[2], "cb": fit[3], "a": t, "e": e})
                result[b] = (fit[0], fit[1], g["o"], t, e); ok = True; break
            future = sorted({pl["e"] for pl in placed if pl["e"] > t})
            t = future[0] if future else (max([t] + [pl["e"] for pl in placed]) + 1)
        if not ok:
            return None
    if b3 and _t.monotonic() < deadline - 1.0:
        tt = solve_timing(prob, bay_id, result, deadline, min(8.0, deadline - _t.monotonic()))
        if tt is not None:
            result = tt
    return result


def pack_windowed_4d(prob, bay_id, ids, time_budget, orient_of, K=18, batch_s=8.0, ncand=2):
    """New B2 doing FULL 4D greedy: (x, y, ORIENT, entry) jointly per batch via
    solve_subset_4d (orient selectors), earlier batches frozen. orient_of seeds the
    candidate set (baseline orient always included). Then caller applies B3."""
    import time as _t
    deadline = _t.monotonic() + float(time_budget)
    geo, W, H = _geo4(prob, bay_id, ids, orient_of, ncand)
    if geo is None:
        return None
    Tub = max(g["R"] for g in geo.values()) + sum(g["P"] for g in geo.values())
    order = sorted(ids, key=lambda b: (geo[b]["D"], geo[b]["R"]))
    frozen = []; placement = {}; i = 0
    while i < len(order):
        if _t.monotonic() >= deadline - 0.5:
            return None
        batch = order[i:i + K]; i += K
        sub = solve_subset_4d(batch, geo, W, H, Tub, frozen,
                              min(batch_s, deadline - _t.monotonic() - 0.5))
        if sub is None:
            return None
        for b in batch:
            x, y, o, e, ex = sub[b]
            placement[b] = (x, y, o, e, ex)
            frozen.append({"entry": e, "exit": ex,
                           "wrects": [(x + r[0], y + r[1], x + r[2], y + r[3])
                                      for r in geo[b]["orients"][o][1]]})
    return placement


def pack_iterative_b2b3(prob, bay_id, ids, time_budget, max_iter=6, b3_s=6.0):
    """User idea (2026-06-18): coordinate-descent B2<->B3. B2 decode (positions) ->
    B3 optimal re-time -> B2 again ORDERED BY B3's entry times -> B3 -> repeat until
    the order converges. Keep best per-bay z1 (obj-gated, never-worse)."""
    import time as _t
    deadline = _t.monotonic() + float(time_budget)
    blocks = prob["blocks"]; bay = Bay.from_dict(prob["bays"][bay_id], bay_id)
    order = sorted(ids, key=lambda b: (blocks[b]["due_date"], blocks[b]["release_time"]))
    best = None; best_z1 = float("inf"); hist = []
    for it in range(max_iter):
        if _t.monotonic() >= deadline - b3_s - 0.5:
            break
        asgn, _ft = ff._fixed_time_decode(bay, bay_id, ids, blocks,
                                          _t.monotonic() + max(2.0, deadline - _t.monotonic() - b3_s),
                                          order_key=list(order))
        if asgn is None:
            break
        place = {b: (asgn[b]["x"], asgn[b]["y"], asgn[b]["orient_idx"],
                     asgn[b]["entry_time"], asgn[b]["exit_time"]) for b in ids}
        timed = solve_timing(prob, bay_id, place, _t.monotonic() + b3_s, b3_s)
        if timed is not None:
            place = timed
        z1 = sum(max(0, place[b][4] - blocks[b]["due_date"]) for b in ids)
        hist.append(int(z1))
        if z1 < best_z1:
            best_z1 = z1; best = place
        new_order = sorted(ids, key=lambda b: (place[b][3], place[b][4]))
        if new_order == order:
            break                      # converged
        order = new_order
    return best, best_z1, hist
