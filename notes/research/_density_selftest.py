"""H0/H1 single-bay DENSITY self-test (run via env python directly).

The H0 wall: both packers are Bottom-Left first-feasible greedy → leave gaps →
over-spill → z3 loss. This test measures the density lever DIRECTLY and apples-to-
apples as: **minimum strip WIDTH to pack a bay's full member set at the bay's
HEIGHT** (footprint-disjoint = crane-safe). Lower width = denser packing.

  - BL baseline: greedy `_bl_fit_cells` into an (almost) unbounded-width strip.
  - spyrrow (if installed): `StripPackingInstance(strip_height=H).solve(...)`.

If spyrrow's width < BL's width on a congested bay, H1 (denser nesting → less
spill → lower z3) is supported and worth integrating. If used_width <= bay.width
the whole member set is co-present-feasible (⇒ z1=0 for that bay).

  FS_TL=20 python notes/research/_density_selftest.py prob_13 prob_14 prob_20

Reports per congested bay: H, bay.width, n_members, member footprint area,
BL strip width, spyrrow strip width (+ density), and whether each fits in bay.width.
"""
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import boxsolver as BS                       # noqa: E402
from utils import Bay, Block                 # noqa: E402

BIG_W = 10_000_000                           # "unbounded" strip width for BL


def _orients(b, bd):
    """Orientation indices with a non-empty footprint, fewest-cells (densest) first."""
    oris = []
    for oi in range(len(bd.get("shape", []) or [])):
        cells, _cb = BS._footprint_cells(b, bd, oi)
        if cells:
            oris.append((len(cells), oi))
    oris.sort()
    return [oi for _, oi in oris]


def bl_strip_width(members, blocks, H):
    """Greedy BL pack of ALL members into a strip of height H, ~unbounded width.
    Returns (used_width, n_placed, placed_cell_area)."""
    copres = []                              # (cells, cellbox)
    used = 0
    placed = 0
    area = 0
    # densest (most cells) first tends to BL-pack tighter
    order = sorted(members, key=lambda b: -len(BS._footprint_cells(b, blocks[b],
                   _orients(b, blocks[b])[0])[0]) if _orients(b, blocks[b]) else 0)
    for b in order:
        bd = blocks[b]
        fit = None
        for oi in _orients(b, bd):
            fit = BS._bl_fit_cells(b, bd, oi, copres, BIG_W, H)
            if fit is not None:
                break
        if fit is None:
            continue                         # taller than H or no slot (rare for strip)
        x, y, scells, scb = fit
        copres.append((scells, scb))
        placed += 1
        area += len(scells)
        used = max(used, scb[2] + 1)
    return used, placed, area


def _outline(b, bd, oi):
    """Largest exterior ring of the orientation's footprint union, as [(x,y),...],
    normalised to origin. Returns (ring, w, h) or None."""
    from shapely.ops import unary_union
    from utils import _poly_from_verts
    layers = Block(b, bd, 0, 0, oi).layers_at_pos()
    polys = [p for p in (_poly_from_verts(l) for l in layers) if p is not None]
    if not polys:
        return None
    u = unary_union(polys)
    geom = max(u.geoms, key=lambda g: g.area) if u.geom_type == "MultiPolygon" else u
    x0, y0, x1, y1 = geom.bounds
    ring = [(x - x0, y - y0) for (x, y) in geom.exterior.coords]
    if len(ring) < 4:
        return None
    return ring, (x1 - x0), (y1 - y0)


def _best_fit_outline(b, bd, H):
    """Among orientations, the footprint outline with the SMALLEST bbox height that
    is <= H (so it can be strip-packed at height H). Returns ring or None."""
    best = None
    for oi in range(len(bd.get("shape", []) or [])):
        o = _outline(b, bd, oi)
        if o is None:
            continue
        ring, w, h = o
        if h <= H + 1e-6 and (best is None or h < best[1]):
            best = (ring, h)
    return best[0] if best else None


def spyrrow_strip_width(members, blocks, H, tl):
    """spyrrow strip pack of ALL members at height H. Returns (width, density) or
    (None, reason)."""
    try:
        import spyrrow
    except Exception as e:                   # not installed yet
        return None, f"import-fail: {e}"
    items = []
    skipped = 0
    for b in members:
        bd = blocks[b]
        ring = _best_fit_outline(b, bd, H)       # height-fitting orientation only
        if ring is None:
            skipped += 1
            continue
        try:                                     # [0,180] = height-preserving flips
            items.append(spyrrow.Item(f"b{b}", shape=ring, demand=1,
                                      allowed_orientations=[0, 180]))
        except Exception as e:
            return None, f"Item-ctor-fail: {e}"
    if not items:
        return None, "no-items"
    try:
        inst = spyrrow.StripPackingInstance("bay", strip_height=float(H), items=items)
        cfg = spyrrow.StripPackingConfig(total_computation_time=int(max(2, tl)),
                                         num_workers=1, seed=42)
        sol = inst.solve(cfg)
        return float(sol.width), float(getattr(sol, "density", float("nan")))
    except BaseException as e:                    # pyo3 PanicException is BaseException
        return None, f"solve-fail: {type(e).__name__}: {str(e)[:80]}"


def main():
    TL = float(os.environ.get("FS_TL", "15"))
    targets = sys.argv[1:] or ["prob_13"]
    print(f"density self-test  TL={TL}  (BL strip-width vs spyrrow strip-width @ bay height)")
    for name in targets:
        prob = json.load(open(ROOT / "instances" / "train" / f"{name}.json", encoding="utf-8"))
        blocks = prob["blocks"]
        bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
        BS._FP_CACHE.clear()
        if hasattr(BS, "_LAYER_CACHE"):
            BS._LAYER_CACHE.clear()
        _placements, members = BS._assign_preferred(blocks, bays)
        # most-congested bays by member count
        ranked = sorted(range(len(bays)), key=lambda j: -len(members[j]))[:3]
        print(f"\n=== {name}: {len(blocks)} blocks, {len(bays)} bays ===")
        for j in ranked:
            mem = members[j]
            if len(mem) < 2:
                continue
            bay = bays[j]
            H, Wbay = bay.height, bay.width
            t0 = time.monotonic()
            blw, bln, blarea = bl_strip_width(mem, blocks, H)
            bldt = time.monotonic() - t0
            t0 = time.monotonic()
            spw, spd = spyrrow_strip_width(mem, blocks, H, TL)
            spdt = time.monotonic() - t0
            footarea = sum(len(BS._footprint_cells(b, blocks[b], _orients(b, blocks[b])[0])[0])
                           for b in mem if _orients(b, blocks[b]))
            bl_fit = "FITS-BAY" if blw <= Wbay else f">bay({blw - Wbay})"
            if spw is not None:
                ratio = (1 - spw / blw) * 100 if blw else 0
                sp_fit = "FITS-BAY" if spw <= Wbay else f">bay({spw - Wbay:.0f})"
                print(f"  bay{j:>3} H={H} Wbay={Wbay} mem={len(mem)} foot={footarea} "
                      f"| BL w={blw} ({bln}/{len(mem)}, {bl_fit}, {bldt:.1f}s) "
                      f"| SPY w={spw:.0f} dens={spd:.2f} ({sp_fit}, {spdt:.1f}s) "
                      f"| denser={ratio:+.0f}%")
            else:
                print(f"  bay{j:>3} H={H} Wbay={Wbay} mem={len(mem)} foot={footarea} "
                      f"| BL w={blw} ({bln}/{len(mem)}, {bl_fit}, {bldt:.1f}s) "
                      f"| SPY={spd}")


if __name__ == "__main__":
    main()
