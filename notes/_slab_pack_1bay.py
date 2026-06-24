"""Single-bay offline test: does the polygon-tight SLAB cover beat the BBOX cover
at reducing tardiness on a REAL stuck bay?

Takes a cached solution, extracts the blocks assigned to a given bay (with their
release/due/processing), and runs two per-bay CP-SAT packers on exactly those
blocks: (1) single-bbox footprint, (2) best-of-H/V 3-slab rectilinear cover
(union >= polygon, conservative).  Reports min-tardiness each achieves.

If slab-pack reaches 0 tardiness where bbox-pack cannot, the lever is worth
wiring into the solver.  Run:
  conda run -n ogc2025 python notes/_slab_pack_1bay.py prob_13 3
"""
import sys, math
sys.path.insert(0, "tools")
import ogc_analysis as A
from shapely.geometry import box, Polygon
from shapely.ops import unary_union
from ortools.sat.python import cp_model


def _footprint_poly(orient):
    polys = []
    for layer in orient["layers"]:
        if len(layer) >= 3:
            p = Polygon(layer)
            if not p.is_valid:
                p = p.buffer(0)
            if p.area > 0:
                polys.append(p)
    return unary_union(polys) if polys else None


def _slabs(poly, n, axis):
    minx, miny, maxx, maxy = poly.bounds
    if poly.area / max(1e-9, (maxx - minx) * (maxy - miny)) >= 0.90:
        return [(math.floor(minx), math.floor(miny),
                 math.ceil(maxx), math.ceil(maxy))]
    bands = []
    for s in range(n):
        if axis == "h":
            lo = miny + (maxy - miny) * s / n
            hi = miny + (maxy - miny) * (s + 1) / n
            clip = poly.intersection(box(minx - 1, lo, maxx + 1, hi))
            if clip.is_empty:
                continue
            cx0, _, cx1, _ = clip.bounds
            bands.append([math.floor(cx0), math.floor(lo),
                          math.ceil(cx1), math.ceil(hi)])
        else:
            lo = minx + (maxx - minx) * s / n
            hi = minx + (maxx - minx) * (s + 1) / n
            clip = poly.intersection(box(lo, miny - 1, hi, maxy + 1))
            if clip.is_empty:
                continue
            _, cy0, _, cy1 = clip.bounds
            bands.append([math.floor(lo), math.floor(cy0),
                          math.ceil(hi), math.ceil(cy1)])
    if not bands:
        return None
    merged = [bands[0]]
    for bd in bands[1:]:
        last = merged[-1]
        if axis == "h" and bd[0] == last[0] and bd[2] == last[2]:
            last[3] = bd[3]
        elif axis == "v" and bd[1] == last[1] and bd[3] == last[3]:
            last[2] = bd[2]
        else:
            merged.append(bd)
    return [tuple(b) for b in merged]


def cover_for(blk, mode):
    """Return (list of int offset rects, orient_idx).  mode in {bbox, slab}."""
    g = A.block_min_area_orient(blk)
    oi = g["orient"]
    poly = _footprint_poly(blk["shape"][oi])
    if poly is None:
        return None, oi
    minx, miny, maxx, maxy = poly.bounds
    bbox = (math.floor(minx), math.floor(miny), math.ceil(maxx), math.ceil(maxy))
    if mode == "bbox":
        return [bbox], oi
    ch = _slabs(poly, 3, "h")
    cv = _slabs(poly, 3, "v")
    cands = [c for c in (ch, cv) if c]
    if not cands:
        return [bbox], oi
    area = lambda c: sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in c)
    return min(cands, key=area), oi


def pack_bay(prob, ids, W, H, mode, budget):
    """Min-tardiness CP-SAT for `ids` in a W x H bay using `mode` footprints.
    Footprint-disjoint-when-time-overlap (crane-safe).  Returns total tardiness
    or None."""
    blocks = prob["blocks"]
    m = cp_model.CpModel()
    covers = {}
    for b in ids:
        cov, oi = cover_for(blocks[b], mode)
        if cov is None:
            return None
        covers[b] = cov
    Ht = max(int(blocks[b]["due_date"]) for b in ids) + \
        sum(int(blocks[b]["processing_time"]) for b in ids)
    rx = {}; ry = {}; e = {}; tard = []
    for b in ids:
        cov = covers[b]
        cminx = min(r[0] for r in cov); cmaxx = max(r[2] for r in cov)
        cminy = min(r[1] for r in cov); cmaxy = max(r[3] for r in cov)
        loX = -cminx; hiX = W - cmaxx
        loY = -cminy; hiY = H - cmaxy
        if hiX < loX or hiY < loY:
            return None
        R = int(blocks[b]["release_time"]); P = int(blocks[b]["processing_time"])
        D = int(blocks[b]["due_date"])
        rx[b] = m.NewIntVar(loX, hiX, f"rx{b}")
        ry[b] = m.NewIntVar(loY, hiY, f"ry{b}")
        e[b] = m.NewIntVar(R, Ht, f"e{b}")
        tv = m.NewIntVar(0, Ht, f"t{b}")
        m.Add(tv >= e[b] + P - D)
        tard.append(tv)
    ids = list(ids)
    for ia in range(len(ids)):
        a = ids[ia]; Pa = int(blocks[a]["processing_time"])
        for ib in range(ia + 1, len(ids)):
            b = ids[ib]; Pb = int(blocks[b]["processing_time"])
            tb = m.NewBoolVar(""); bt = m.NewBoolVar("")
            m.Add(e[a] + Pa <= e[b]).OnlyEnforceIf(tb)
            m.Add(e[b] + Pb <= e[a]).OnlyEnforceIf(bt)
            sd = m.NewBoolVar("")  # spatially disjoint (every cover-rect pair sep)
            for (ax0, ay0, ax1, ay1) in covers[a]:
                for (bx0, by0, bx1, by1) in covers[b]:
                    l = m.NewBoolVar(""); r = m.NewBoolVar("")
                    bel = m.NewBoolVar(""); ab = m.NewBoolVar("")
                    m.Add(rx[a] + ax1 <= rx[b] + bx0).OnlyEnforceIf(l)
                    m.Add(rx[b] + bx1 <= rx[a] + ax0).OnlyEnforceIf(r)
                    m.Add(ry[a] + ay1 <= ry[b] + by0).OnlyEnforceIf(bel)
                    m.Add(ry[b] + by1 <= ry[a] + ay0).OnlyEnforceIf(ab)
                    m.AddBoolOr([l, r, bel, ab]).OnlyEnforceIf(sd)
            m.AddBoolOr([tb, bt, sd])
    m.Minimize(sum(tard))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(budget)
    s.parameters.num_search_workers = 4
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return sum(s.Value(t) for t in tard), st == cp_model.OPTIMAL


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "prob_13"
    bay_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    prob = A.load_instance(name)
    sol = A.load_solution(f"results/_z0_{name}.json")
    rec = A.assignments(prob, sol)
    ids = sorted(b for b, r in rec.items() if r["bay"] == bay_idx)
    bay = prob["bays"][bay_idx]
    W, H = int(bay["width"]), int(bay["height"])
    # current tardiness in this bay
    cur = sum(max(0, rec[b]["exit"] - rec[b]["due"]) for b in ids)
    print(f"{name} bay {bay_idx}: {len(ids)} blocks, {W}x{H}, "
          f"current_tardiness={cur}")
    for mode in ("bbox", "slab"):
        out = pack_bay(prob, ids, W, H, mode, budget)
        if out is None:
            print(f"  {mode:5}: no solution")
        else:
            t, opt = out
            print(f"  {mode:5}: tardiness={t}  {'(OPTIMAL)' if opt else '(feasible)'}")


if __name__ == "__main__":
    main()
