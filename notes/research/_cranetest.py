"""Isolate: on the PREFERRED (z3≈0) assignment, does the crane-overlap packer
reach lower z1 than the cells packer? (the cycle-9 hypothesis)."""
import json, sys, time
from pathlib import Path
ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
import ogc_analysis as OA
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M
from utils import Bay

names = sys.argv[1:] or ['prob_3', 'prob_4', 'prob_9', 'prob_11', 'prob_15', 'prob_16']
BUD = 40.0
print(f"{'inst':<9}{'mode':>7}{'feas':>6}{'z1':>9}{'z3':>8}{'obj':>14}{'wall':>7}")
for name in names:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    _, members = M._assign_preferred(blocks, bays)
    for mode in ('cells', 'crane'):
        M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
        placements = {}
        t0 = time.monotonic()
        pt = M._pack_all(members, placements, bays, blocks, t0 + BUD, mode=mode)
        dt = time.monotonic() - t0
        if pt is None or len(pt) != n:
            print(f"{name:<9}{mode:>7}{'FAIL':>6}")
            continue
        sol = M._build(placements, pt, n)
        feas, obj, z1, z2, z3 = OA.obj_tuple(prob, sol)
        print(f"{name:<9}{mode:>7}{str(feas):>6}{z1:>9.0f}{z3:>8.0f}{obj:>14.0f}{dt:>7.1f}")
