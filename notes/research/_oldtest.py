"""Run the ARCHIVED old solver (archive/old-solver-src-2026-06-14) on set1 instances
to confirm it realizes z1=0 at low z3 (the thing the fresh-start box-decomp can't).
Run via env python directly. The old myalgorithm auto-injects its best config at T>=60.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))           # ogc_analysis (may poison path)
import ogc_analysis as OA                          # noqa: E402
sys.path.insert(0, str(ROOT / 'src'))              # utils (official)
sys.path.insert(0, str(ROOT / 'archive' / 'old-solver-src-2026-06-14'))  # OLD myalgorithm = path[0]
import myalgorithm as M                            # noqa: E402  (the OLD solver)

TL = float(os.environ.get('OLD_TL', '200'))
targets = sys.argv[1:] or ['prob_12', 'prob_13', 'prob_14', 'prob_20']
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
c12 = json.load(open('notes/research/baselines/c12.json'))
print(f"OLD solver from: {M.__file__}")
print(f"TL={TL}")
print(f"{'inst':<9}{'obj':>13}{'z1':>7}{'z3':>8}{'wall':>7}{'comp':>11}{'c12':>13}  res")
tot = 0.0
for name in targets:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    t0 = time.monotonic()
    try:
        sol = M.algorithm(prob, TL)
        feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
    except Exception as e:
        print(f"{name:<9}  ERROR {type(e).__name__}: {e}")
        continue
    dt = time.monotonic() - t0
    tot += o
    cm = COMP.get(name, {}).get('obj'); co = c12.get(name, {}).get('obj')
    tag = 'BEAT-COMP' if (cm and o < cm) else ''
    flag = '  *WALL>TL*' if dt > TL + 5 else ''
    print(f"{name:<9}{o:>13.0f}{z1:>7.0f}{z3:>8.0f}{dt:>7.1f}{(cm or 0):>11.0f}"
          f"{(co or 0):>13.0f}  {tag}{flag}", flush=True)
print(f"TOTAL={tot:.0f}")
