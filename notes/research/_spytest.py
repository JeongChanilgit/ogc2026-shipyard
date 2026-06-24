"""H1 verification: does spyrrow (SOTA nester) pack a congested bay's block
footprints much denser than our bottom-left greedy? If spyrrow fits the same blocks
into far less than the bay width, our BL is wasting space (over-spilling → high z3).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'notes' / 'research'))    # freshstart
import spyrrow                                          # noqa: E402
import freshstart as FS                                 # noqa: E402
from utils import Bay, Block, _poly_from_verts          # noqa: E402
from shapely.ops import unary_union                     # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else 'prob_20'
TL = int(sys.argv[2]) if len(sys.argv) > 2 else 12
prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
blocks = prob['blocks']
bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]


def footprint(b):
    """Min-orientation footprint polygon (union of layers projected). Returns
    exterior coords + area, or None."""
    best = None
    for oi in range(len(blocks[b].get('shape', []) or [])):
        polys = [p for p in (_poly_from_verts(l)
                 for l in Block(b, blocks[b], 0, 0, oi).layers_at_pos()) if p is not None]
        if not polys:
            continue
        u = unary_union(polys)
        g = u.convex_hull if u.geom_type == 'MultiPolygon' else u
        try:
            coords = list(g.exterior.coords)[:-1]
        except Exception:
            continue
        if best is None or g.area < best[1]:
            best = (coords, g.area)
    return best


# assign each block to most-preferred bay (z3=0) → pick the most-loaded bay
nb = len(bays)
_, mem = FS._assign_preferred(blocks, bays)
j = max(range(nb), key=lambda k: len(mem[k]))
W, H = bays[j].width, bays[j].height
ids = list(mem[j])
print(f"[{name}] congested bay {j}: {len(ids)} blocks, bay WxH = {W:.0f}x{H:.0f} = {W*H:.0f}")

items = []
tot_area = 0.0
for b in ids:
    fp = footprint(b)
    if fp is None:
        continue
    coords, area = fp
    tot_area += area
    items.append(spyrrow.Item(str(b), [(float(x), float(y)) for x, y in coords],
                              1, [0.0, 90.0, 180.0, 270.0]))
print(f"items={len(items)}  total footprint area={tot_area:.0f}  "
      f"(area/bay = {100*tot_area/(W*H):.0f}%; >100% means cannot all be co-present)")

inst = spyrrow.StripPackingInstance("", float(H), items)
cfg = spyrrow.StripPackingConfig(total_computation_time=TL, seed=1, num_workers=4)
t0 = time.monotonic()
sol = inst.solve(cfg)
dt = time.monotonic() - t0
used_w = max((getattr(p, 'translation', (0, 0))[0] for p in sol.placed_items), default=0)
# spyrrow solution: report achieved strip width (the metric it minimises)
W_ach = getattr(sol, 'width', None) or getattr(sol, 'strip_width', None) or used_w
util = 100 * tot_area / (W_ach * H) if W_ach else 0
print(f"spyrrow: placed={len(sol.placed_items)}  achieved_width={W_ach:.1f}  "
      f"(bay W={W:.0f})  utilization={util:.0f}%  wall={dt:.1f}s")
print(f">>> spyrrow fits these blocks in width {W_ach:.0f} vs bay width {W:.0f} "
      f"— {'TIGHTER (room to spare)' if W_ach < W else 'needs more than bay'}")
print("sol attrs:", [a for a in dir(sol) if not a.startswith('_')])
