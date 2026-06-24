"""Prototype + verify the rectilinear (horizontal-slab) cover that will replace
the single bbox footprint in the polygon-tight packer.

Checks, on real instance blocks:
  (1) CONSERVATIVE: union of slab rectangles CONTAINS the true footprint polygon
      (required for official feasibility safety).
  (2) TIGHTER: total slab area < bbox area (the waste we want to recover).
Run: conda run -n ogc2025 python notes/_slab_cover_proto.py
"""
import sys, math, glob, json
sys.path.insert(0, "tools")
import ogc_analysis as A
from shapely.geometry import box, Polygon
from shapely.ops import unary_union


def _footprint_poly(orient):
    """Shapely union of an orientation's layers in LOCAL coords (ref = as given)."""
    polys = []
    for layer in orient["layers"]:
        if len(layer) >= 3:
            p = Polygon(layer)
            if p.is_valid and p.area > 0:
                polys.append(p)
            elif not p.is_valid:
                p = p.buffer(0)
                if p.area > 0:
                    polys.append(p)
    if not polys:
        return None
    return unary_union(polys)


def rect_cover(orient, n_slabs):
    """Return a list of (x0,y0,x1,y1) integer-outward slab rectangles whose union
    CONTAINS the footprint polygon.  Slabs split the y-range into n_slabs bands;
    each band's x-extent is the polygon's exact extent there (outward-rounded).
    Adjacent bands with equal rounded x-extent are merged.  n_slabs auto-drops to
    1 (=bbox) for near-rectangular shapes."""
    poly = _footprint_poly(orient)
    if poly is None:
        return None, None
    minx, miny, maxx, maxy = poly.bounds
    bbox_area = (maxx - minx) * (maxy - miny)
    if bbox_area <= 0:
        return None, None
    # near-rectangular -> single bbox slab
    fill = poly.area / bbox_area
    if fill >= 0.90 or n_slabs <= 1:
        return [(math.floor(minx), math.floor(miny),
                 math.ceil(maxx), math.ceil(maxy))], poly
    bands = []
    for s in range(n_slabs):
        ylo = miny + (maxy - miny) * s / n_slabs
        yhi = miny + (maxy - miny) * (s + 1) / n_slabs
        clip = poly.intersection(box(minx - 1, ylo, maxx + 1, yhi))
        if clip.is_empty:
            continue
        cx0, _, cx1, _ = clip.bounds
        bands.append([math.floor(cx0), math.floor(ylo),
                      math.ceil(cx1), math.ceil(yhi)])
    if not bands:
        return None, None
    # merge vertically-adjacent bands with identical x-extent
    merged = [bands[0]]
    for bd in bands[1:]:
        last = merged[-1]
        if bd[0] == last[0] and bd[2] == last[2]:
            last[3] = bd[3]
        else:
            merged.append(bd)
    return [tuple(b) for b in merged], poly


def rect_cover_vert(orient, n_slabs):
    """Vertical-slab variant: split the x-range into bands, y-extent per band."""
    poly = _footprint_poly(orient)
    if poly is None:
        return None, None
    minx, miny, maxx, maxy = poly.bounds
    bbox_area = (maxx - minx) * (maxy - miny)
    if bbox_area <= 0:
        return None, None
    if poly.area / bbox_area >= 0.90 or n_slabs <= 1:
        return [(math.floor(minx), math.floor(miny),
                 math.ceil(maxx), math.ceil(maxy))], poly
    bands = []
    for s in range(n_slabs):
        xlo = minx + (maxx - minx) * s / n_slabs
        xhi = minx + (maxx - minx) * (s + 1) / n_slabs
        clip = poly.intersection(box(xlo, miny - 1, xhi, maxy + 1))
        if clip.is_empty:
            continue
        _, cy0, _, cy1 = clip.bounds
        bands.append([math.floor(xlo), math.floor(cy0),
                      math.ceil(xhi), math.ceil(cy1)])
    if not bands:
        return None, None
    merged = [bands[0]]
    for bd in bands[1:]:
        last = merged[-1]
        if bd[1] == last[1] and bd[3] == last[3]:
            last[2] = bd[2]
        else:
            merged.append(bd)
    return [tuple(b) for b in merged], poly


def _cover_area(cover):
    return sum((x1 - x0) * (y1 - y0) for (x0, y0, x1, y1) in cover)


def main():
    for name in ["prob_11", "prob_13", "prob_20"]:
        prob = A.load_instance(name)
        configs = {"H3": ("h", 3), "H6": ("h", 6), "V3": ("v", 3),
                   "best3": ("best", 3), "best6": ("best", 6)}
        sums = {k: 0.0 for k in configs}
        tot_bbox = tot_poly = 0.0
        viol = {k: 0 for k in configs}
        rects = {k: 0 for k in configs}
        for blk in prob["blocks"]:
            g = A.block_min_area_orient(blk)
            orient = blk["shape"][g["orient"]]
            poly = _footprint_poly(orient)
            if poly is None:
                continue
            minx, miny, maxx, maxy = poly.bounds
            bbox_area = (math.ceil(maxx) - math.floor(minx)) * \
                        (math.ceil(maxy) - math.floor(miny))
            tot_bbox += bbox_area
            tot_poly += poly.area
            for k, (axis, ns) in configs.items():
                if axis == "h":
                    cov, _ = rect_cover(orient, ns)
                elif axis == "v":
                    cov, _ = rect_cover_vert(orient, ns)
                else:  # best of h/v
                    ch, _ = rect_cover(orient, ns)
                    cv, _ = rect_cover_vert(orient, ns)
                    cov = min([c for c in (ch, cv) if c],
                              key=_cover_area, default=None)
                if cov is None:
                    continue
                sums[k] += _cover_area(cov)
                rects[k] += len(cov)
                union = unary_union([box(*r) for r in cov])
                if poly.difference(union).area > 1e-6:
                    viol[k] += 1
        print(f"\n{name}: bbox_sum={tot_bbox:.0f} poly_sum={tot_poly:.0f} "
              f"(poly is {100*tot_poly/tot_bbox:.0f}% of bbox = floor)")
        for k in configs:
            print(f"   {k:6} area={sums[k]:.0f} "
                  f"reduction={100*(1-sums[k]/tot_bbox):5.1f}% "
                  f"(of recoverable {100*(1-sums[k]/tot_bbox)/(1-tot_poly/tot_bbox):4.0f}%) "
                  f"avg_rects={rects[k]/len(prob['blocks']):.1f} viol={viol[k]}")


if __name__ == "__main__":
    main()
