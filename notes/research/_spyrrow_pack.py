"""H1 INTEGRATION PROTOTYPE — spyrrow dense layout + timing-oracle decoupling.

The old solver's win = DECOUPLE: fix a crane-safe layout, then schedule timing on
the fixed layout. This replaces the BL layout with a much DENSER spyrrow layout:

  1. preferred assignment (z3≈0) → members per bay.
  2. per bay: FFD-group members into WxH-feasible CO-PRESENT groups, using spyrrow
     as the dense bin-packer (group accepted iff its blocks pack within [0,W]x[0,H]).
     Every block gets a fixed (x,y,oi). Within-group footprints are disjoint
     (co-present-able); cross-group blocks reuse the bay area (time-disjoint).
  3. timing oracle (greedy EDD-with-conflicts): each block enters at the earliest
     time >= release when its footprint cells are free of co-present blocks. Denser
     layout ⇒ more disjoint pairs ⇒ more co-presence ⇒ lower tardiness.

Co-present footprint-disjoint ⇒ crane-safe by construction (same invariant the
existing packers + official checker rely on). Falls back to per-bay EDD serialise
if a bay's spyrrow layout fails the official check (never −1).

  SPY_TL=1.0 DENS=0.75 python notes/research/_spyrrow_pack.py prob_13
"""
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as OA                      # noqa: E402
sys.path.insert(0, str(ROOT / "src"))
import boxsolver as BS                         # noqa: E402
from utils import Bay, Block, check_feasibility  # noqa: E402

SPY_TL = float(os.environ.get("SPY_TL", "1.0"))      # legacy (unused in 1-strip mode)
BAY_TL = float(os.environ.get("BAY_TL", "5.0"))      # spyrrow seconds per bay
SEP = float(os.environ.get("SEP", "0.0"))            # min item separation
DENS = float(os.environ.get("DENS", "0.78"))


def _block_info(b, bd, W, H):
    """Choose the orientation that fits WxH with the SMALLEST footprint height
    (maximizes how many columns fit). Returns dict or None if none fits."""
    from shapely.ops import unary_union
    from utils import _poly_from_verts
    best = None
    for oi in range(len(bd.get("shape", []) or [])):
        layers = Block(b, bd, 0, 0, oi).layers_at_pos()
        polys = [p for p in (_poly_from_verts(l) for l in layers) if p is not None]
        if not polys:
            continue
        u = unary_union(polys)
        geom = max(u.geoms, key=lambda g: g.area) if u.geom_type == "MultiPolygon" else u
        gx0, gy0, gx1, gy1 = geom.bounds
        w, h = gx1 - gx0, gy1 - gy0
        if w > W + 1e-6 or h > H + 1e-6:
            continue
        if best is None or h < best["h"]:
            cells, cb = BS._footprint_cells(b, bd, oi)
            ring = [(x - gx0, y - gy0) for (x, y) in geom.exterior.coords]
            best = {"oi": oi, "gx0": gx0, "gy0": gy0, "w": w, "h": h,
                    "ring": ring, "cells": cells, "cb": cb, "area": len(cells)}
    return best


def _spyrrow_layout(grp, info, H, tl):
    """Pack group `grp` into a height-H strip. Returns {b:(tx,ty)} or None."""
    try:
        import spyrrow
    except Exception:
        return None
    items = []
    for b in grp:
        ring = info[b]["ring"]
        if len(ring) < 4:
            return None
        items.append(spyrrow.Item(f"b{b}", shape=ring, demand=1,
                                  allowed_orientations=[0]))
    try:
        inst = spyrrow.StripPackingInstance("bay", strip_height=float(H), items=items)
        cfg = spyrrow.StripPackingConfig(total_computation_time=max(2, int(round(tl))),
                                         num_workers=1, seed=42,
                                         min_items_separation=SEP)
        sol = inst.solve(cfg)
    except BaseException:
        return None
    pos = {}
    for pi in sol.placed_items:
        b = int(pi.id[1:])
        pos[b] = (float(pi.translation[0]), float(pi.translation[1]))
    return pos if len(pos) == len(grp) else None


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def pack_bay(members, blocks, bay, deadline):
    """ONE spyrrow strip pack of ALL members at height H, then slice the strip into
    W-wide columns (`bay_x = sx mod W`) so blocks get DIVERSE bay positions (not
    stacked) → far fewer forced overlaps. Returns ({b:(x,y,oi)}, info) or None."""
    W, H = int(bay.width), int(bay.height)
    info = {}
    for b in members:
        bi = _block_info(b, blocks[b], W, H)
        if bi is None:
            return None
        info[b] = bi
    pos = _spyrrow_layout(members, info, H, BAY_TL)
    placements = {}
    if pos is None:                           # fallback: BL each block alone (own slot)
        for b in members:
            fit = BS._bl_fit_cells(b, blocks[b], info[b]["oi"], [], W, H)
            if fit:
                placements[b] = (fit[0], fit[1], info[b]["oi"])
            else:
                cb = info[b]["cb"]
                placements[b] = (-cb[0], -cb[1], info[b]["oi"])
        return placements, info
    for b in members:
        tx, ty = pos[b]
        gx0, gy0, fw, cb = info[b]["gx0"], info[b]["gy0"], info[b]["w"], info[b]["cb"]
        c = math.floor(tx / W) if W > 0 else 0
        wfl = tx - c * W                       # wrap into a W-wide column
        if wfl + fw > W:
            wfl = W - fw
        if wfl < 0:
            wfl = 0.0
        X = _clamp(int(round(wfl - gx0)), -cb[0], W - 1 - cb[2])
        Y = _clamp(int(round(ty - gy0)), -cb[1], H - 1 - cb[3])
        placements[b] = (X, Y, info[b]["oi"])
    return placements, info


def _placed_poly(b, bd, oi, X, Y):
    """Exact placed footprint polygon (union of layers at world pos (X,Y))."""
    from shapely.ops import unary_union
    from utils import _poly_from_verts
    layers = Block(b, bd, int(X), int(Y), oi).layers_at_pos()
    polys = [p for p in (_poly_from_verts(l) for l in layers) if p is not None]
    return unary_union(polys) if polys else None


def schedule(placements, info, members, blocks):
    """Greedy EDD timing on the fixed layout, using EXACT-polygon overlap (touching
    footprints do NOT conflict ⇒ dense same-column blocks stay co-present)."""
    polys, bb = {}, {}
    for b in members:
        X, Y, oi = placements[b]
        p = _placed_poly(b, blocks[b], oi, X, Y)
        polys[b] = p
        bb[b] = p.bounds if p is not None else (0, 0, -1, -1)
    ov = {b: set() for b in members}           # exact-overlap adjacency
    ml = list(members)
    for i, a in enumerate(ml):
        if polys[a] is None:
            continue
        ax0, ay0, ax1, ay1 = bb[a]
        for b in ml[i + 1:]:
            if polys[b] is None:
                continue
            bx0, by0, bx1, by1 = bb[b]
            if ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0:
                continue                       # bbox-disjoint prefilter
            if polys[a].intersection(polys[b]).area > 1e-6:
                ov[a].add(b); ov[b].add(a)
    times, placed = {}, []
    for b in sorted(members, key=lambda b: (int(blocks[b]["due_date"]),
                                            int(blocks[b]["release_time"]))):
        R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
        entry = R
        for (pb, pex) in placed:
            if pex > entry and pb in ov[b]:
                entry = pex
        ex = entry + P
        times[b] = (entry, ex)
        placed.append((b, ex))
    return times


def schedule_cpsat(placements, info, members, blocks, time_limit):
    """CP-SAT disjunctive timing oracle on the FIXED layout: minimise Σ tardiness
    s.t. exact-overlapping placed footprints have time-disjoint [entry,exit). This
    is the proven z1→0 mechanism (1-D disjunctive single-machine tardiness). Falls
    back to the greedy schedule on any failure."""
    from ortools.sat.python import cp_model
    polys, bb = {}, {}
    for b in members:
        X, Y, oi = placements[b]
        p = _placed_poly(b, blocks[b], oi, X, Y)
        polys[b] = p
        bb[b] = p.bounds if p is not None else (0, 0, -1, -1)
    ml = list(members)
    edges = []
    for i, a in enumerate(ml):
        if polys[a] is None:
            continue
        ax0, ay0, ax1, ay1 = bb[a]
        for b in ml[i + 1:]:
            if polys[b] is None:
                continue
            bx0, by0, bx1, by1 = bb[b]
            if ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0:
                continue
            if polys[a].intersection(polys[b]).area > 1e-6:
                edges.append((a, b))
    R = {b: int(blocks[b]["release_time"]) for b in members}
    P = {b: int(blocks[b]["processing_time"]) for b in members}
    D = {b: int(blocks[b]["due_date"]) for b in members}
    horizon = max(R.values()) + sum(P.values()) + 1
    m = cp_model.CpModel()
    entry, ivl, tard = {}, {}, {}
    for b in members:
        entry[b] = m.NewIntVar(R[b], horizon, f"e{b}")
        ex = m.NewIntVar(R[b] + P[b], horizon + P[b], f"x{b}")
        m.Add(ex == entry[b] + P[b])
        ivl[b] = m.NewIntervalVar(entry[b], P[b], ex, f"i{b}")
        t = m.NewIntVar(0, horizon + P[b], f"t{b}")
        m.AddMaxEquality(t, [ex - D[b], 0])
        tard[b] = t
    # adjacency → cliques would be tighter, but pairwise NoOverlap is exact + simple
    for (a, b) in edges:
        m.AddNoOverlap([ivl[a], ivl[b]])
    m.Minimize(sum(tard.values()))
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = float(max(2.0, time_limit))
    sv.parameters.num_search_workers = int(os.environ.get("CPW", "4"))
    sv.parameters.random_seed = 42
    st = sv.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return schedule(placements, info, members, blocks)
    return {b: (int(sv.Value(entry[b])), int(sv.Value(entry[b])) + P[b]) for b in members}


def solve(prob, deadline):
    blocks = prob["blocks"]; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    BS._FP_CACHE.clear()
    assign = os.environ.get("ASSIGN", "preferred")
    if assign == "capped":
        _placements, members = BS._assign_capped(blocks, bays, float(os.environ.get("ALPHA", "1.0")))
    elif assign == "balanced":
        _placements, members = BS._assign_balanced(blocks, bays)
    else:
        _placements, members = BS._assign_preferred(blocks, bays)
    pos = {}      # b -> (j, oi, x, y)
    times = {}    # b -> (entry, exit)
    for j, mem in enumerate(members):
        if not mem:
            continue
        res = pack_bay(mem, blocks, bays[j], deadline)
        if res is None:                       # fallback: per-bay EDD serialise
            free = 0
            for b in sorted(mem, key=lambda b: (int(blocks[b]["due_date"]),
                                                int(blocks[b]["release_time"]))):
                R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
                bi = _block_info(b, blocks[b], int(bays[j].width), int(bays[j].height))
                oi = bi["oi"] if bi else 0
                entry = max(R, free); pos[b] = (j, oi, 0, 0)
                times[b] = (entry, entry + P); free = entry + P
            continue
        placements, info = res
        if os.environ.get("ORACLE", "cpsat") == "cpsat":
            t = schedule_cpsat(placements, info, mem, blocks,
                               float(os.environ.get("CPSAT_TL", "8")))
        else:
            t = schedule(placements, info, mem, blocks)
        for b in mem:
            X, Y, oi = placements[b]
            pos[b] = (j, oi, X, Y)
            times[b] = t[b]
    ops = {}
    for b in range(n):
        j, oi, x, y = pos[b]; entry, ex = times[b]
        ops.setdefault(ex, []).append({"type": "EXIT", "block_id": b, "bay_id": int(j)})
        ops.setdefault(entry, []).append({"type": "ENTRY", "block_id": b, "bay_id": int(j),
                                          "x": int(x), "y": int(y), "orient_idx": int(oi)})
    operations = {str(int(t)): [o for o in ops[t] if o["type"] == "EXIT"]
                  + [o for o in ops[t] if o["type"] == "ENTRY"] for t in sorted(ops)}
    return {"operations": operations}


def main():
    TL = float(os.environ.get("FS_TL", "120"))
    targets = sys.argv[1:] or ["prob_13"]
    COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                          encoding="utf-8"))["competitor"]
    HYB = json.load(open(ROOT / "notes" / "research" / "baselines" / "hybrid_set1.json"))
    print(f"spyrrow-pack  SPY_TL={SPY_TL} DENS={DENS} FS_TL={TL}")
    print(f"{'inst':<9}{'obj':>13}{'z1':>7}{'z2':>7}{'z3':>8}{'wall':>7}"
          f"{'hybrid':>12}{'comp':>11}  res")
    for name in targets:
        prob = json.load(open(ROOT / "instances" / "train" / f"{name}.json", encoding="utf-8"))
        t0 = time.monotonic()
        sol = solve(prob, t0 + TL)
        dt = time.monotonic() - t0
        chk = check_feasibility(prob, sol)
        if not chk.get("feasible"):
            print(f"{name:<9}  INFEASIBLE stage={chk.get('stage')} "
                  f"{(chk.get('violations') or ['?'])[:2]}  wall={dt:.1f}")
            continue
        feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
        hy = HYB.get(name, {}).get("obj"); cm = COMP.get(name, {}).get("obj")
        tag = ("BEAT-COMP" if (cm and o < cm) else
               ("beat-hybrid" if (hy and o < hy - 1) else ""))
        print(f"{name:<9}{o:>13.0f}{z1:>7.0f}{z2:>7.0f}{z3:>8.0f}{dt:>7.1f}"
              f"{(hy or 0):>12.0f}{(cm or 0):>11.0f}  {tag}", flush=True)


if __name__ == "__main__":
    main()
