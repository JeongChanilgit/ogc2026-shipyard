"""Test: does a FINER assignment spectrum (capped with various alpha) find the
competitor's regime (small z3 + low z1)? Pack with cells (fast) to scan, report
z1/z3/obj per alpha. preferred = alpha=inf; balanced ~ small alpha."""
import json, sys, time, math
from pathlib import Path
ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
import ogc_analysis as OA
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M
from utils import Bay

names = sys.argv[1:] or ['prob_3', 'prob_9', 'prob_11', 'prob_15', 'prob_16']
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
ALPHAS = [('pref', None), (5.0, 5.0), (3.0, 3.0), (2.0, 2.0), (1.5, 1.5),
          (1.2, 1.2), (1.0, 1.0), (0.8, 0.8)]
for name in names:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    comp = COMP.get(name, {})
    print(f"\n=== {name}  competitor: obj={comp.get('obj',0):.0f} z1={comp.get('z1','?')} "
          f"z3={comp.get('z3','?')}  w1={prob['weights']['w1']} w3={prob['weights']['w3']} ===")
    print(f"  {'alpha':>6}{'z1':>7}{'z3':>8}{'obj':>14}")
    for tag, a in ALPHAS:
        M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
        if a is None:
            _, members = M._assign_preferred(blocks, bays)
        else:
            _, members = M._assign_capped(blocks, bays, a)
        placements = {}
        pt = M._pack_all(members, placements, bays, blocks, time.monotonic() + 25, mode='cells')
        if pt is None or len(pt) != n:
            print(f"  {str(tag):>6}  FAIL"); continue
        sol = M._build(placements, pt, n)
        feas, obj, z1, z2, z3 = OA.obj_tuple(prob, sol)
        win = '  <-- BEAT' if (comp.get('obj') and obj < comp['obj']) else ''
        print(f"  {str(tag):>6}{z1:>7.0f}{z3:>8.0f}{obj:>14.0f}{win}")
