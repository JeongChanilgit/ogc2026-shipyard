"""Decisive diagnostic: does crane-overlap freedom (upper-layer OVERHANG beyond
layer 0) exist in the instances? If layers taper (upper subset of lower), then
crane-safe co-presence == full-footprint-disjoint == what the cells packer already
does → the z1 floor is a SCHEDULING/search problem, not a geometry-permissiveness
one. If significant overhang exists, the official-predicate packer can beat cells."""
import json, sys
from pathlib import Path
ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'src'))
from utils import Block, _poly_from_verts
from shapely.ops import unary_union

names = sys.argv[1:] or ['prob_3', 'prob_4', 'prob_9', 'prob_11', 'prob_15', 'prob_16']
for name in names:
    p = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = p['blocks']
    nlayer_hist = {}
    n_overhang = 0
    tot_oh_frac = 0.0
    n_multi = 0
    max_oh = 0.0
    for b in range(len(blocks)):
        nor = len(blocks[b].get('shape', []) or [])
        # min-area orientation
        best = None
        for oi in range(nor):
            layers = Block(b, blocks[b], 0, 0, oi).layers_at_pos()
            polys = [q for q in (_poly_from_verts(l) for l in layers) if q is not None]
            if not polys:
                continue
            nl = len(polys)
            full = unary_union(polys)
            l0 = polys[0]
            a0 = l0.area
            af = full.area
            if best is None or af < best[1]:
                best = (nl, af, a0, full, l0)
        if best is None:
            continue
        nl, af, a0, full, l0 = best
        nlayer_hist[nl] = nlayer_hist.get(nl, 0) + 1
        if nl >= 2:
            n_multi += 1
            # overhang = area of full footprint NOT covered by layer-0 footprint
            oh = full.difference(l0).area
            frac = oh / af if af > 0 else 0.0
            tot_oh_frac += frac
            max_oh = max(max_oh, frac)
            if frac > 0.01:
                n_overhang += 1
    avg_oh = (tot_oh_frac / n_multi) if n_multi else 0.0
    print(f"{name:<9} nblk={len(blocks):>3} layers={nlayer_hist} "
          f"multi-layer={n_multi} | OVERHANG blocks(>1%)={n_overhang} "
          f"avg_oh_frac={avg_oh:.3f} max_oh_frac={max_oh:.3f}")
