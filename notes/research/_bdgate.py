"""Box-decomp long-TL gate on the 5 hard targets (full algorithm(), BD on vs off).
Run twice: OGC_BOXDECOMP=0 then =1, same GATE_TL. MUST have __main__ guard (spawn
pool re-imports). Saves notes/research/_bd_<tag>.json."""
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
    TL = float(os.environ.get('GATE_TL', '180'))
    tag = os.environ.get('OGC_BOXDECOMP', '0')
    targets = ['prob_11', 'prob_12', 'prob_13', 'prob_14', 'prob_20']
    COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
    c12 = json.load(open('notes/research/baselines/c12.json'))
    print(f"BD={tag} TL={TL}")
    print(f"{'inst':<9}{'obj':>13}{'z1':>7}{'z3':>8}{'c12_obj':>13}{'comp':>11}{'wall':>7}")
    out = {}
    tot = 0.0
    for name in targets:
        prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
        t0 = time.monotonic()
        sol = M.algorithm(prob, TL)
        dt = time.monotonic() - t0
        feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
        tot += o
        out[name] = {"feas": bool(feas), "obj": o, "z1": z1, "z2": z2, "z3": z3,
                     "wall": round(dt, 1)}
        co = c12.get(name, {}).get('obj')
        cm = COMP.get(name, {}).get('obj')
        print(f"{name:<9}{o:>13.0f}{z1:>7.0f}{z3:>8.0f}{(co or 0):>13.0f}"
              f"{(cm or 0):>11.0f}{dt:>7.1f}", flush=True)
    print(f"TOTAL(5)={tot:.0f}")
    json.dump({"tag": tag, "tl": TL, "rows": out, "total5": tot},
              open(f'notes/research/_bd_{tag}.json', 'w'), indent=0)


if __name__ == "__main__":
    main()
