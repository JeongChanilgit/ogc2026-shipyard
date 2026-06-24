"""Map the spill->obj frontier: for a target, sweep capped-alpha (∞=preferred ...
small=more spill), pack each with box-decomp+cumulative, report (z3, z1, obj).
The min-obj point IS our achievable floor. If z1 only hits ~0 at heavy spill
(z3~9000) -> goal unreachable; if z1 hits ~0 at z3~1000 -> big win possible.
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

os.environ.setdefault('OGC_BD_CUMUL', '1')
TARGET = sys.argv[1] if len(sys.argv) > 1 else 'prob_13'
PACKTL = float(os.environ.get('SC_PACKTL', '60'))
ALPHAS = [float(a) for a in os.environ.get(
    'SC_ALPHAS', 'inf,3.0,2.0,1.5,1.2,1.0,0.85').split(',')]
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
c12 = json.load(open('notes/research/baselines/c12.json'))

prob = json.load(open(f'instances/train/{TARGET}.json', encoding='utf-8'))
blocks = prob['blocks']; n = len(blocks)
bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
cm = COMP.get(TARGET, {}).get('obj'); co = c12.get(TARGET, {}).get('obj')
print(f"[{TARGET}] comp_obj={cm}  c12_obj={co}  PACKTL={PACKTL}  cumul={os.environ['OGC_BD_CUMUL']}")
print(f"{'alpha':>7}{'z1':>7}{'z2':>7}{'z3':>8}{'obj':>13}  vs_comp")
for a in ALPHAS:
    M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
    if a == float('inf'):
        _, members = M._assign_preferred(blocks, bays)
    else:
        _, members = M._assign_capped(blocks, bays, a)
    mem_lists = [list(m) for m in members]
    r = M._pack_members(mem_lists, bays, blocks, n, prob,
                        time.monotonic() + PACKTL, 'boxdecomp')
    if r is None:
        print(f"{a:>7}  None/infeasible")
        continue
    obj, sol = r
    feas, o2, z1, z2, z3 = OA.obj_tuple(prob, sol)
    tag = 'BEAT-COMP' if (cm and o2 < cm) else ('beat-c12' if (co and o2 < co - 1) else '')
    print(f"{a:>7.2f}{z1:>7.0f}{z2:>7.0f}{z3:>8.0f}{o2:>13.0f}  {tag}")
