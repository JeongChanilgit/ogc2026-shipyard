"""Offline check of the _bay_wants_slab routing decision (pure geometry, no
solver).  For a solution's tardy bays, report bbox vs cover area-demand peak at
[release,due] and the route the live router would pick.  Verifies prob_13's tight
bay -> slab while prob_6/9 (easy) and prob_20 (over-capacity) -> bbox."""
import sys, math, os
sys.path.insert(0, "tools")
import ogc_analysis as A
from shapely.geometry import box, Polygon
from shapely.ops import unary_union


def _foot_poly(orient):
    polys = []
    for layer in orient["layers"]:
        if len(layer) >= 3:
            p = Polygon(layer)
            if not p.is_valid:
                p = p.buffer(0)
            if p.area > 0:
                polys.append(p)
    return unary_union(polys) if polys else None


def cover_area(blk, oi, n=3):
    poly = _foot_poly(blk["shape"][oi])
    if poly is None:
        return None
    minx, miny, maxx, maxy = poly.bounds
    bbox_a = (math.ceil(maxx) - math.floor(minx)) * (math.ceil(maxy) - math.floor(miny))
    if (maxx - minx) * (maxy - miny) <= 0 or poly.area / ((maxx-minx)*(maxy-miny)) >= 0.90:
        return bbox_a
    best = bbox_a
    for axis in ("h", "v"):
        bands = []
        for s in range(n):
            if axis == "h":
                lo = miny + (maxy-miny)*s/n; hi = miny + (maxy-miny)*(s+1)/n
                clip = poly.intersection(box(minx-1, lo, maxx+1, hi))
                if clip.is_empty: continue
                cx0,_,cx1,_ = clip.bounds
                bands.append([math.floor(cx0),math.floor(lo),math.ceil(cx1),math.ceil(hi)])
            else:
                lo = minx + (maxx-minx)*s/n; hi = minx + (maxx-minx)*(s+1)/n
                clip = poly.intersection(box(lo, miny-1, hi, maxy+1))
                if clip.is_empty: continue
                _,cy0,_,cy1 = clip.bounds
                bands.append([math.floor(lo),math.floor(cy0),math.ceil(hi),math.ceil(cy1)])
        if bands:
            a = sum((x1-x0)*(y1-y0) for x0,y0,x1,y1 in bands)
            best = min(best, a)
    return best


def peak(ev):
    ev = sorted(ev, key=lambda x:(x[0], x[1]))
    cur=pk=0.0
    for _t,da in ev: cur+=da; pk=max(pk,cur)
    return pk


def check(inst, sol_path):
    prob = A.load_instance(inst); sol = A.load_solution(sol_path)
    rec = A.assignments(prob, sol)
    nb = len(prob["bays"])
    print(f"\n{inst} ({sol_path}):")
    for j in range(nb):
        ids = sorted(b for b,r in rec.items() if r["bay"]==j)
        if not ids: continue
        bay = prob["bays"][j]; W=int(bay["width"]);H=int(bay["height"]); area=W*H
        cur_t = sum(max(0, rec[b]["exit"]-rec[b]["due"]) for b in ids)
        ev_bb=[]; ev_cov=[]
        for b in ids:
            blk=prob["blocks"][b]
            g=A.block_min_area_orient(blk); oi=g["orient"]
            bb=A._block_bbox if False else None
            # bbox area via ogc geometry
            og=A.orient_geometry(blk["shape"][oi]); bbox_a=og["bbox_area"]
            cov_a=cover_area(blk, oi)
            s=blk["release_time"]; e=blk["due_date"]
            if e<=s: e=s+max(1,blk["processing_time"])
            ev_bb+=[(s,bbox_a),(e,-bbox_a)]; ev_cov+=[(s,cov_a),(e,-cov_a)]
        bpk=peak(ev_bb); cpk=peak(ev_cov)
        wants = (len(ids)<=110) and bpk>area and cpk<=area
        tag = "SLAB" if wants else "bbox"
        flag = "  <-- tardy" if cur_t>0 else ""
        print(f"  bay{j} n={len(ids):3} area={area:6} bbox_dmd={100*bpk/area:5.0f}% "
              f"cov_dmd={100*cpk/area:5.0f}% cur_tard={cur_t:4.0f} -> {tag}{flag}")


if __name__ == "__main__":
    for inst, p in [("prob_6","results/_solo_prob_6_slabOFF.json"),
                    ("prob_9","results/_solo_prob_9_slabOFF.json"),
                    ("prob_13","results/_z0_prob_13.json"),
                    ("prob_20","results/_z0_prob_20.json")]:
        if os.path.exists(p):
            check(inst, p)
