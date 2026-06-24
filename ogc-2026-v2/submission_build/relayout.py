"""Post-hoc per-bay RELAYOUT polish (2026-06-18; moved from notes/research/perbay).

Re-lays-out each TARDY bay with best-of {windowed fixed-orient, windowed 4D-orient}
CP-SAT + B3 timing oracle; swaps the bay's layout IFF its per-bay z1 strictly
improves (official check downstream + obj-gated -> NEVER worse, never -1).
Post-hoc validation: full set2 271.93M -> 269.33M (-2.6M, competitor lead -7.89M
-> -10.49M). Gated final stage (OGC_RELAYOUT). Bays are spatially independent so a
bay's z1 reduction lowers instance obj directly (z2/z3 invariant within a bay).
"""
from __future__ import annotations
import os, time
import boxsolver as bx
from utils import Bay
from baseline_greedy import _build_operations


def _parse_sol(sol):
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


def _build_sol(place):
    flat = [{"block_id": b, "bay_id": p["bay"], "x": p["x"], "y": p["y"],
             "orient_idx": p["orient"], "entry_time": p["entry"],
             "exit_time": p["exit"]} for b, p in place.items()]
    return {"operations": _build_operations(flat)}


def polish(prob, sol, time_budget, per_bay=6.0, z1min=20):
    """Final per-bay relayout polish. time_budget = leftover wall (seconds)."""
    deadline = time.monotonic() + float(time_budget)
    blocks = prob["blocks"]
    place = _parse_sol(sol)
    byb = {}
    for b, p in place.items():
        byb.setdefault(p["bay"], []).append(b)
    # worst (most-tardy) bays first so the limited budget hits the biggest z1
    bay_z1 = {j: sum(max(0, place[b]["exit"] - blocks[b]["due_date"]) for b in ids)
              for j, ids in byb.items()}
    for j in sorted(byb, key=lambda j: -bay_z1[j]):
        ids = byb[j]
        if time.monotonic() >= deadline - per_bay - 0.5:
            break
        if len(ids) < 2 or bay_z1[j] <= z1min:
            continue
        oof = {b: place[b]["orient"] for b in ids}
        best = None; bz1 = bay_z1[j]
        try:
            l1 = pack_windowed_cpsat(prob, j, ids, time.monotonic() + per_bay, oof, K=30, batch_s=5)
        except Exception:
            l1 = None
        try:
            l2 = pack_windowed_4d(prob, j, ids, per_bay, oof, K=18, batch_s=5, ncand=2)
        except Exception:
            l2 = None
        for lay in (l1, l2):
            if lay is None:
                continue
            t = solve_timing(prob, j, lay, time.monotonic() + 5, 5.0) or lay
            z1 = sum(max(0, t[b][4] - blocks[b]["due_date"]) for b in ids)
            if z1 < bz1:
                bz1 = z1; best = t
        if best is not None:
            for b in ids:
                x, y, o, e, ex = best[b]
                place[b].update(x=x, y=y, orient=o, entry=e, exit=ex)
    return _build_sol(place)


# ===== extracted packers (from packers_cpsat.py) =====

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
