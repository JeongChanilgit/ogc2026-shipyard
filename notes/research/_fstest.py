"""Quick single/few-instance runner for the integrated pipeline (run via env python
directly — conda run crashes with 4-worker CP-SAT). Reports obj/z1/z3/wall + vs c12/comp.
  FS_TL=150 python notes/research/_fstest.py prob_13 prob_14
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


def main():
    TL = float(os.environ.get('FS_TL', '150'))
    targets = sys.argv[1:] or ['prob_13']
    COMP = json.load(open('notes/competitor-2026-06-15.json', encoding='utf-8'))['competitor']
    c12 = json.load(open('notes/research/baselines/c12.json'))
    print(f"TL={TL}  FEASSPILL={os.environ.get('OGC_FEASSPILL')}  BOXDECOMP={os.environ.get('OGC_BOXDECOMP')}")
    print(f"{'inst':<9}{'obj':>13}{'z1':>7}{'z3':>8}{'wall':>7}{'c12':>13}{'comp':>11}  res")
    tot = 0.0
    for name in targets:
        prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
        t0 = time.monotonic()
        sol = M.algorithm(prob, TL)
        dt = time.monotonic() - t0
        feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
        tot += o
        co = c12.get(name, {}).get('obj'); cm = COMP.get(name, {}).get('obj')
        tag = 'BEAT-COMP' if (cm and o < cm) else ('beat-c12' if (co and o < co - 1) else '')
        flag = '  *** WALL>TL ***' if dt > TL + 3 else ''
        print(f"{name:<9}{o:>13.0f}{z1:>7.0f}{z3:>8.0f}{dt:>7.1f}{(co or 0):>13.0f}"
              f"{(cm or 0):>11.0f}  {tag}{flag}", flush=True)
    print(f"TOTAL={tot:.0f}")


if __name__ == '__main__':
    main()
