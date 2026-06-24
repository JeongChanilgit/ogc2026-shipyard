"""Per-bay EXACT CP-SAT 2D bounding-box packing + tardiness scheduling.

A deliberate structural addition -- the architecture's unbuilt "W3 small-bay
CP-SAT exact" lever.  The greedy fixed-time decoder
(`fastfloor._fixed_time_decode`) places blocks one at a time at BL spots and
leaves gaps; for a congested bay that gap structure forces some blocks to wait
(tardiness).  This module instead JOINTLY optimises every co-bay block's
(position, orientation, entry-time) with CP-SAT to MINIMISE the bay's total
tardiness, fitting more blocks at z1=0 than the greedy decoder.

WHY BOUNDING-BOX PACKING IS CRANE-SAFE (the geometric fact that validates it):
a block's axis-aligned bounding BOX contains its polygon (utils.Block /
Bay.contains_block rely on the same superset property).  So if the bounding
BOXES of two co-present blocks do not overlap, their polygons cannot overlap
either, AND every crane descent column of one is clear of the other.  Hence a
bounding-box-disjoint arrangement is GUARANTEED crane-feasible -- conservative
(it may fit fewer blocks than an optimal polygon packing, because boxes waste
the concave slack), but every solution it finds is a valid one.  The final
arrangement is still re-verified with the real checker
(`utils.check_feasibility`) so the conservatism is never trusted blindly.

Self-contained: imports ortools cp_model + fastfloor / myalgorithm / utils
only, modifies none.

    C:/Users/peter/anaconda3/envs/ogc2025/python.exe src/baypack_cp.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ortools.sat.python import cp_model                          # noqa: E402

import fastfloor as FF                                           # noqa: E402
import myalgorithm as M                                          # noqa: E402
import utils                                                     # noqa: E402
from utils import Bay, Block                                     # noqa: E402


# ---------------------------------------------------------------------------
# Per-block orientation candidates: integer bbox (w, h) + reference offset.
#
# The record stores x/y as the REFERENCE point (first vertex of first layer =
# local (0,0)); the polygon's local bbox `pb = _block_bbox(blk, oi)` may have a
# non-zero (and negative) minimum.  So the world bbox of a placement at
# reference (dx, dy) spans [dx + pb0, dx + pb2] x [dx... wait y] etc.  We model
# the world bbox LEFT/BOTTOM edge (px, py) directly in CP-SAT (clean [0, W-w]
# range), then recover the reference coordinate dx = px - pb0, dy = py - pb1
# for the output record.  Containment 0 <= dx+pb0 and dx+pb2 <= W  <=>
# 0 <= px and px + w <= W.
# ---------------------------------------------------------------------------

def _orient_boxes(blk: dict):
    """Candidate orientations of ``blk`` as a list of
    (orient_idx, w, h, off_x, off_y) where (w, h) is the integer bounding-box
    size and (off_x, off_y) = local bbox minimum (pb0, pb1) -- the offset to
    convert a world bbox bottom-left edge into the stored reference x/y.

    Uses ceil(w)/ceil(h) for the box size and floor(pb) for the offset so the
    integerised box is a conservative SUPERSET of the float polygon bbox (never
    smaller than reality -> never claims a tighter fit than exists)."""
    out = []
    geo = FF._ft_geom(blk)
    nshape = len(blk.get("shape", []) or [])
    for oi in range(nshape):
        g = geo[oi] if oi < len(geo) else None
        if g is None:
            continue                                  # un-rasterisable orient
        pb = g[2]                                      # float local poly bbox
        off_x = int(math.floor(pb[0]))
        off_y = int(math.floor(pb[1]))
        w = int(math.ceil(pb[2])) - off_x
        h = int(math.ceil(pb[3])) - off_y
        if w <= 0 or h <= 0:
            continue
        out.append((oi, w, h, off_x, off_y))
    return out


# ---------------------------------------------------------------------------
# Exact per-bay CP-SAT pack + schedule.
# ---------------------------------------------------------------------------

def pack_bay_cp(prob_info, bay, bay_idx, block_ids, deadline,
                time_budget=10.0):
    """Jointly optimise (position, orientation, entry-time) for ``block_ids`` in
    ``bay`` to MINIMISE total tardiness, with bounding-box non-overlap for
    co-present blocks (crane-safe by the box-contains-polygon property).

    Returns ``(result_dict | None, tardiness)``:
      * result_dict = {block_id: {block_id, bay_id, x, y, orient_idx,
                                  entry_time, exit_time}} on success,
      * tardiness   = total sum of max(0, exit - due) over the blocks,
      * (None, inf) iff CP-SAT proves infeasible or finds NO solution.

    CP-SAT returns feasible incumbents under the time limit; the best one found
    is handed back (its tardiness is an upper bound, exact only if proven
    OPTIMAL)."""
    ids = list(block_ids)
    if not ids:
        return {}, 0.0
    blocks = prob_info["blocks"]
    W = int(bay.width)
    H = int(bay.height)

    # Per-block orientation candidates (bbox + offset).  A block with no
    # rasterisable orientation that fits the bay at all makes the bay infeasible.
    cand = {}
    for b in ids:
        boxes = [(oi, w, h, ox, oy) for (oi, w, h, ox, oy) in _orient_boxes(blocks[b])
                 if w <= W and h <= H]
        if not boxes:
            return None, math.inf
        cand[b] = boxes

    # Horizon: latest a block could need to enter and still be scheduled.  A
    # generous slack bound (max due + sum of processing) is always enough to
    # serialise everything; CP-SAT prunes within it.
    max_due = max(int(blocks[b]["due_date"]) for b in ids)
    sum_P = sum(int(blocks[b]["processing_time"]) for b in ids)
    horizon = max_due + sum_P + 1

    m = cp_model.CpModel()

    o_lit = {}    # (b, oi) -> BoolVar  (orientation chosen)
    wv = {}       # b -> IntVar bbox width  (channelled to chosen orient)
    hv = {}       # b -> IntVar bbox height
    offx = {}     # b -> IntVar reference x-offset (off_x of chosen orient)
    offy = {}     # b -> IntVar reference y-offset
    px = {}       # b -> IntVar world bbox left edge   in [0, W-w]
    py = {}       # b -> IntVar world bbox bottom edge in [0, H-h]
    entry = {}    # b -> IntVar entry time
    exitv = {}    # b -> IntVar exit time = entry + P
    td = {}       # b -> IntVar tardiness >= 0

    for b in ids:
        blk = blocks[b]
        R = int(blk["release_time"]); P = int(blk["processing_time"])
        D = int(blk["due_date"])
        boxes = cand[b]

        lits = []
        for (oi, w, h, ox, oy) in boxes:
            lit = m.NewBoolVar(f"o_{b}_{oi}")
            o_lit[b, oi] = lit
            lits.append(lit)
        m.Add(sum(lits) == 1)

        ws = [w for (_, w, _, _, _) in boxes]
        hs = [h for (_, _, h, _, _) in boxes]
        oxs = [ox for (_, _, _, ox, _) in boxes]
        oys = [oy for (_, _, _, _, oy) in boxes]
        wv[b] = m.NewIntVar(min(ws), max(ws), f"w_{b}")
        hv[b] = m.NewIntVar(min(hs), max(hs), f"h_{b}")
        offx[b] = m.NewIntVar(min(oxs), max(oxs), f"ox_{b}")
        offy[b] = m.NewIntVar(min(oys), max(oys), f"oy_{b}")
        # Channel the geometry vars to the chosen orientation literal.
        for k, (oi, w, h, ox, oy) in enumerate(boxes):
            lit = o_lit[b, oi]
            m.Add(wv[b] == w).OnlyEnforceIf(lit)
            m.Add(hv[b] == h).OnlyEnforceIf(lit)
            m.Add(offx[b] == ox).OnlyEnforceIf(lit)
            m.Add(offy[b] == oy).OnlyEnforceIf(lit)

        px[b] = m.NewIntVar(0, W, f"px_{b}")
        py[b] = m.NewIntVar(0, H, f"py_{b}")
        m.Add(px[b] + wv[b] <= W)                      # right wall
        m.Add(py[b] + hv[b] <= H)                       # top wall

        entry[b] = m.NewIntVar(R, horizon, f"e_{b}")
        exitv[b] = m.NewIntVar(R + P, horizon + P, f"x_{b}")
        m.Add(exitv[b] == entry[b] + P)
        tv = m.NewIntVar(0, horizon + P, f"t_{b}")
        m.Add(tv >= exitv[b] - D)                       # tv >= 0 by domain
        td[b] = tv

    # Pairwise non-overlap: either the world bounding BOXES are spatially
    # disjoint (one of left/right/below/above), OR the time intervals are
    # disjoint (before/after).  Box-disjoint => polygon-disjoint AND crane
    # columns clear, so this is sufficient for crane-feasibility.
    n = len(ids)
    for ii in range(n):
        for jj in range(ii + 1, n):
            bi = ids[ii]; bj = ids[jj]
            left = m.NewBoolVar(f"L_{bi}_{bj}")    # i left of j
            right = m.NewBoolVar(f"R_{bi}_{bj}")   # i right of j
            below = m.NewBoolVar(f"B_{bi}_{bj}")   # i below j
            above = m.NewBoolVar(f"A_{bi}_{bj}")   # i above j
            before = m.NewBoolVar(f"T_{bi}_{bj}")  # i exits before j enters
            after = m.NewBoolVar(f"F_{bi}_{bj}")   # j exits before i enters
            m.Add(px[bi] + wv[bi] <= px[bj]).OnlyEnforceIf(left)
            m.Add(px[bj] + wv[bj] <= px[bi]).OnlyEnforceIf(right)
            m.Add(py[bi] + hv[bi] <= py[bj]).OnlyEnforceIf(below)
            m.Add(py[bj] + hv[bj] <= py[bi]).OnlyEnforceIf(above)
            m.Add(exitv[bi] <= entry[bj]).OnlyEnforceIf(before)
            m.Add(exitv[bj] <= entry[bi]).OnlyEnforceIf(after)
            m.AddBoolOr([left, right, below, above, before, after])

    # Hints: greedy-style entry=R, BL-ish px=py=0, first orientation.
    for b in ids:
        R = int(blocks[b]["release_time"])
        m.AddHint(entry[b], R)
        oi0 = cand[b][0][0]
        m.AddHint(o_lit[b, oi0], 1)

    m.Minimize(sum(td[b] for b in ids))

    s = cp_model.CpSolver()
    # Respect both the per-bay budget and the global wall deadline.
    rem = max(0.2, deadline - time.monotonic()) if deadline else float(time_budget)
    s.parameters.max_time_in_seconds = max(0.2, min(float(time_budget), rem))
    s.parameters.num_search_workers = 4
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, math.inf

    result = {}
    total_t = 0.0
    for b in ids:
        # Recover chosen orientation + reference (x, y) from the world bbox edge.
        oi_sel = None
        for (oi, _, _, _, _) in cand[b]:
            if s.Value(o_lit[b, oi]) == 1:
                oi_sel = oi
                break
        if oi_sel is None:
            oi_sel = cand[b][0][0]
        ox = s.Value(offx[b]); oy = s.Value(offy[b])
        rx = int(s.Value(px[b])) - int(ox)            # reference x = px - off_x
        ry = int(s.Value(py[b])) - int(oy)
        e = int(s.Value(entry[b])); x_ = int(s.Value(exitv[b]))
        D = int(blocks[b]["due_date"])
        total_t += max(0.0, x_ - D)
        result[b] = {"block_id": b, "bay_id": bay_idx, "x": rx, "y": ry,
                     "orient_idx": int(oi_sel),
                     "entry_time": e, "exit_time": x_}
    return result, total_t


# ---------------------------------------------------------------------------
# Thin improver wrapper: keep the CP-SAT layout only if it lowers tardiness.
# ---------------------------------------------------------------------------

def _records_tard(records, blocks):
    return sum(max(0.0, int(a["exit_time"]) - int(blocks[b]["due_date"]))
               for b, a in records.items())


def improve_bay(prob_info, bays, bay_idx, current_records, blocks, deadline,
                time_budget):
    """Run ``pack_bay_cp`` on the bay's current block set; return the NEW records
    iff their tardiness is strictly lower than ``current_records``' (else the
    unchanged ``current_records``).

    ``current_records`` = {block_id: record} for bay ``bay_idx``."""
    if not current_records:
        return current_records
    cur_tard = _records_tard(current_records, blocks)
    if cur_tard <= 0.0:
        return current_records                         # already optimal (z1=0)
    new_recs, new_tard = pack_bay_cp(prob_info, bays[bay_idx], bay_idx,
                                     list(current_records.keys()), deadline,
                                     time_budget=time_budget)
    if new_recs is None or new_tard >= cur_tard - 1e-9:
        return current_records
    return new_recs


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _make_bays_and_u(prob):
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    areas = [prob["bays"][j]["width"] * prob["bays"][j]["height"]
             for j in range(nb)]
    avg = sum(areas) / nb
    bay_u = [avg / a for a in areas]
    return bays, bay_u


def _boxes_disjoint(prob_info, bay_idx, records):
    """Direct crane-safety confirmation of a packed bay via the box-disjoint
    property: every pair of TIME-OVERLAPPING blocks must have disjoint bounding
    boxes.  Returns (ok, n_violations).  This is what makes the polygon + crane
    constraints trivially satisfied."""
    blocks = prob_info["blocks"]
    items = list(records.items())
    viol = 0
    for i in range(len(items)):
        bi, ai = items[i]
        bli = Block(bi, blocks[bi], int(ai["x"]), int(ai["y"]),
                    int(ai["orient_idx"]))
        rbi = bli.bounding_rect()
        ei0, ei1 = int(ai["entry_time"]), int(ai["exit_time"])
        for jj in range(i + 1, len(items)):
            bj, aj = items[jj]
            ej0, ej1 = int(aj["entry_time"]), int(aj["exit_time"])
            if not (ei0 < ej1 and ej0 < ei1):
                continue                               # time-disjoint -> safe
            blj = Block(bj, blocks[bj], int(aj["x"]), int(aj["y"]),
                        int(aj["orient_idx"]))
            rbj = blj.bounding_rect()
            # boxes disjoint iff one is fully to a side of the other
            if (rbi[2] <= rbj[0] or rbj[2] <= rbi[0]
                    or rbi[3] <= rbj[1] or rbj[3] <= rbi[1]):
                continue
            viol += 1
    return viol == 0, viol


def _selftest():
    import json

    insts = ["prob_11", "prob_17", "prob_6"]
    BAY_BUDGET = 15.0

    print("=" * 104)
    print("baypack_cp self-test  -- greedy fixed-time decode vs exact CP-SAT "
          "bounding-box pack, per congested bay")
    print("=" * 104)

    any_win = False
    any_verified = False
    big_bay_note = []

    for inst in insts:
        path = _ROOT / "instances" / "train" / f"{inst}.json"
        prob = json.load(open(path, encoding="utf-8"))
        blocks = prob["blocks"]
        bays, bay_u = _make_bays_and_u(prob)
        nb = len(bays)

        # z3-optimal assignment -> per-bay membership.
        try:
            feas = M._feasible_bays(blocks, bays)
        except Exception:
            feas = [list(range(nb)) for _ in blocks]
        feas = [(f if f else list(range(nb))) for f in feas]
        try:
            assign = M._cpsat_assignment(prob, bays, feas, bay_u,
                                         time_budget=20.0)
        except Exception:
            assign = None
        if assign is None:
            assign = FF._greedy_assign(blocks, feas, prob["bays"])
        members = {j: [] for j in range(nb)}
        for b, j in enumerate(assign):
            if 0 <= j < nb:
                members[j].append(b)

        # Greedy fixed-time decode each bay; the CONGESTED bays are the ones the
        # greedy leaves tardy.
        deadline = time.monotonic() + 1e9
        congested = []
        greedy_tard = {}
        for j in range(nb):
            if len(members[j]) < 2:
                continue
            res, ft = FF._fixed_time_decode(bays[j], j, members[j], blocks,
                                            deadline, order_key="F0")
            gt = ft["ft_tard"] if res is not None else math.inf
            greedy_tard[j] = gt
            if gt > 1e-9:
                congested.append(j)

        print(f"\n### {inst}  (bays={nb}, blocks={len(blocks)})  "
              f"congested bays={congested}")
        if not congested:
            print("    (greedy already z1=0 on every bay -- no congested bay)")
            continue

        print(f"    {'bay':>4} {'n_blk':>6} {'greedy_td':>10} {'cp_td':>10} "
              f"{'cp_wall':>8} {'cp<grd':>7} {'boxes_ok':>9} {'viol':>5}")
        print("    " + "-" * 70)
        for j in sorted(congested):
            mem = members[j]
            gt = greedy_tard[j]
            t0 = time.monotonic()
            cp_dl = time.monotonic() + BAY_BUDGET + 2.0
            cp_recs, cp_t = pack_bay_cp(prob, bays[j], j, mem, cp_dl,
                                        time_budget=BAY_BUDGET)
            wall = time.monotonic() - t0
            # Flag only bays that ACTUALLY saturated the budget (incumbent, not
            # proven optimal) -- a fast finish means CP-SAT closed the gap.
            if wall >= BAY_BUDGET - 0.5:
                big_bay_note.append((inst, j, len(mem), wall))
            if cp_recs is None:
                print(f"    {j:>4} {len(mem):>6} {gt:>10.0f} {'NONE':>10} "
                      f"{wall:>8.1f} {'--':>7} {'--':>9} {'--':>5}")
                continue
            better = cp_t < gt - 1e-9
            ok, viol = _boxes_disjoint(prob, j, cp_recs)
            if better:
                any_win = True
            if ok and cp_recs:
                any_verified = True
            print(f"    {j:>4} {len(mem):>6} {gt:>10.0f} {cp_t:>10.0f} "
                  f"{wall:>8.1f} {('yes' if better else 'no'):>7} "
                  f"{str(ok):>9} {viol:>5}")

    # Full-solution feasibility confirmation: build a complete solution where
    # every congested bay is replaced by its CP-SAT layout, the rest greedy,
    # then run the OFFICIAL checker on prob_11.
    print("\n" + "=" * 104)
    print("FULL-SOLUTION FEASIBILITY CHECK (official utils.check_feasibility)")
    print("=" * 104)
    inst = "prob_11"
    prob = json.load(open(_ROOT / "instances" / "train" / f"{inst}.json",
                          encoding="utf-8"))
    blocks = prob["blocks"]
    bays, bay_u = _make_bays_and_u(prob)
    nb = len(bays)
    try:
        feas = M._feasible_bays(blocks, bays)
    except Exception:
        feas = [list(range(nb)) for _ in blocks]
    feas = [(f if f else list(range(nb))) for f in feas]
    assign = M._cpsat_assignment(prob, bays, feas, bay_u, time_budget=20.0)
    if assign is None:
        assign = FF._greedy_assign(blocks, feas, prob["bays"])
    members = {j: [] for j in range(nb)}
    for b, j in enumerate(assign):
        members[j].append(b)
    deadline = time.monotonic() + 1e9
    all_recs = {}
    used_cp = 0
    for j in range(nb):
        if len(members[j]) < 1:
            continue
        res, ft = FF._fixed_time_decode(bays[j], j, members[j], blocks,
                                        deadline, order_key="F0")
        if res is None:
            all_recs[j] = None
            continue
        if ft["ft_tard"] > 1e-9 and len(members[j]) >= 2:
            cp_dl = time.monotonic() + 17.0
            cp_recs, cp_t = pack_bay_cp(prob, bays[j], j, members[j], cp_dl,
                                        time_budget=15.0)
            if cp_recs is not None and cp_t < ft["ft_tard"] - 1e-9:
                res = cp_recs
                used_cp += 1
        all_recs[j] = res

    if any(v is None for v in all_recs.values()):
        print("  (some bay failed to decode -- skipping full-sol check)")
    else:
        flat = [a for by in all_recs.values() for a in by.values()]
        sol = {"operations": M._build_operations(flat)}
        try:
            chk = utils.check_feasibility(prob, sol)
            feasible = bool(chk.get("feasible", chk.get("is_feasible", False))
                            if isinstance(chk, dict) else chk)
        except Exception as ex:
            feasible = False
            print(f"  checker raised: {ex!r}")
        comp = M._components_from_solution(prob, sol, bay_u)
        print(f"  {inst}: CP-SAT used on {used_cp} bay(s), "
              f"full-sol feasible={feasible}")
        if comp is not None:
            print(f"         obj={comp[0]:.0f}  z1={comp[1]:.0f}  "
                  f"z2={comp[2]:.1f}  z3={comp[3]:.0f}")
        if feasible:
            any_verified = True

    # Verdict.
    print("\n" + "=" * 104)
    print("VERDICT")
    print(f"  CP-SAT packs >=1 congested bay with LOWER tardiness : {any_win}")
    print(f"  arrangement verifies crane-feasible                 : {any_verified}")
    if big_bay_note:
        print("  bays that SATURATED the budget (incumbent only, not proven "
              "optimal -- CP-SAT intractable at this size):")
        for inst, j, n, wall in big_bay_note:
            print(f"    {inst} bay {j}: {n} blocks, {wall:.1f}s wall "
                  f"(hit the {BAY_BUDGET:.0f}s budget)")
    else:
        print("  (no congested bay saturated the budget in this test)")
    print(f"  SUCCESS = {any_win and any_verified}")
    print("=" * 104)


if __name__ == "__main__":
    _selftest()
