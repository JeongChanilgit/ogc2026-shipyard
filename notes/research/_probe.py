import json, os, sys, time
from pathlib import Path
ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
import ogc_analysis as OA
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M

if __name__ == "__main__":      # GUARD: without this, spawn workers re-run the body
    name = sys.argv[1]
    TL = float(sys.argv[2])
    # OGC_CPSAT already set in env by caller; _spec_list() reads it at call time.
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    t0 = time.monotonic()
    sol = M.algorithm(prob, TL)
    dt = time.monotonic() - t0
    feas, obj, z1, z2, z3 = OA.obj_tuple(prob, sol)
    tag = 'cpsat' if os.environ.get('OGC_CPSAT', '1') not in ('0', 'false', 'off') else 'base'
    print(f"{name:<9}{tag:>7}  feas={feas!s:<5} obj={obj:>14.0f}  z1={z1:>8.0f}  "
          f"z3={z3:>7.0f}  wall={dt:>5.1f}s", flush=True)
