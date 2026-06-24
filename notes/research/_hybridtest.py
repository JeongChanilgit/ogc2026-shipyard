"""Confirm the hybrid gain: does fresh-start box-decomp beat the restored old solver
on prob_3/4/18 (lower z3 at z1=0) at the SAME TL=200? Old-solver gate numbers:
prob_3=76630, prob_4=46011, prob_18=105596."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))
import ogc_analysis as OA                                # noqa: E402
sys.path.insert(0, str(ROOT / 'src'))                    # utils
sys.path.insert(0, str(ROOT / 'notes' / 'research'))     # freshstart (box-decomp)
import freshstart as FS                                  # noqa: E402

os.environ.setdefault('OGC_BOXDECOMP', '1')
os.environ.setdefault('OGC_FEASSPILL', '0')
TL = float(os.environ.get('HT_TL', '200'))
OLD = {'prob_3': 76630, 'prob_4': 46011, 'prob_18': 105596}
targets = sys.argv[1:] or ['prob_3', 'prob_4', 'prob_18']
print(f"fresh-start box-decomp @TL={TL}  (vs old solver gate)")
print(f"{'inst':<9}{'obj':>12}{'z1':>6}{'z3':>8}{'wall':>7}{'old':>10}  res")
for name in targets:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    t0 = time.monotonic()
    sol = FS.algorithm(prob, TL)
    dt = time.monotonic() - t0
    feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
    old = OLD.get(name)
    tag = 'BEATS-OLD' if (old and o < old - 1) else ('worse' if old and o > old + 1 else '')
    print(f"{name:<9}{o:>12.0f}{z1:>6.0f}{z3:>8.0f}{dt:>7.1f}{(old or 0):>10}  {tag}", flush=True)
