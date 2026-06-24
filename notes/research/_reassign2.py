"""Isolated test of the cycle-10 reassignment solver vs c8 + competitor."""
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
TL = 60.0
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
c8 = json.load(open('notes/research/baselines/c8.json'))
print(f"{'inst':<9}{'z1':>7}{'z3':>8}{'obj':>13}{'c8_obj':>13}{'comp_obj':>11}{'wall':>7}  res")
for name in names:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
    t0 = time.monotonic()
    r = M._solve_reassign(prob, blocks, bays, t0 + TL * 0.85)
    dt = time.monotonic() - t0
    if r is None:
        print(f"{name:<9}  None"); continue
    obj, sol = r
    feas, o2, z1, z2, z3 = OA.obj_tuple(prob, sol)
    co = c8.get(name, {}).get('obj'); cmp = COMP.get(name, {}).get('obj')
    tag = ''
    if cmp and o2 < cmp: tag = 'BEAT-COMP'
    elif co and o2 < co - 1: tag = 'beat-c8'
    elif co and o2 > co + 1: tag = 'WORSE-c8'
    print(f"{name:<9}{z1:>7.0f}{z3:>8.0f}{o2:>13.0f}{(co or 0):>13.0f}"
          f"{(cmp or 0):>11.0f}{dt:>7.1f}  {tag}")
