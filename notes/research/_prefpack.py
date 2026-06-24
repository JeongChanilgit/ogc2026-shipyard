"""Isolate the base PACKER ceiling at the PURE PREFERRED assignment (no reassign).

Energetic (_whyhard.py) says z1=0 is area-feasible at (near-)preferred for the 5
hard instances. This probes what our packers ACTUALLY achieve there, per mode, so
we know whether the lever is (a) packer strength [z1 floors high at preferred] or
(b) the reassign LS over-spilling z3 [packer already near z1=0 at preferred].
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
import ogc_analysis as OA                               # noqa: E402
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M                                 # noqa: E402
from utils import Bay                                   # noqa: E402

os.environ['OGC_CPSAT'] = '1'
TARGETS = sys.argv[1:] or ['prob_11', 'prob_12', 'prob_13', 'prob_14', 'prob_20']
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
MODES = os.environ.get('PP_MODES', 'cells,cpsat,lns').split(',')
TLI = float(os.environ.get('PP_TL', '15'))

print(f"{'inst':<9}{'mode':>7}{'z1':>7}{'z2':>7}{'z3':>8}{'obj':>13}"
      f"{'comp_obj':>11}{'wall':>7}")
print('-' * 70)
for name in TARGETS:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']
    n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    cmp = COMP.get(name, {}).get('obj')
    for mode in MODES:
        M._FP_CACHE.clear()
        M._LAYER_CACHE.clear()
        _, members = M._assign_preferred(blocks, bays)
        t0 = time.monotonic()
        r = M._pack_members(members, bays, blocks, n, prob, t0 + TLI, mode)
        dt = time.monotonic() - t0
        if r is None:
            print(f"{name:<9}{mode:>7}   INFEAS/None  wall={dt:.1f}")
            continue
        obj, sol = r
        feas, o2, z1, z2, z3 = OA.obj_tuple(prob, sol)
        print(f"{name:<9}{mode:>7}{z1:>7.0f}{z2:>7.0f}{z3:>8.0f}{o2:>13.0f}"
              f"{(cmp or 0):>11.0f}{dt:>7.1f}")
    print()
