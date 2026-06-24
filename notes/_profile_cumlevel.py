"""Profile where cum_level wall-time goes: CP-SAT cumulative solve vs crane
re-decode (_decode_bay).  Monkeypatches both to accumulate wall-time + call count.
Usage: python notes/_profile_cumlevel.py prob_20 --timelimit 100
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")

import myalgorithm as M
import ogc_analysis as A
from ortools.sat.python import cp_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

# --- accumulators ---
STAT = {"cpsat_t": 0.0, "cpsat_n": 0, "redecode_t": 0.0, "redecode_n": 0}

_orig_solve = cp_model.CpSolver.Solve
def _solve(self, *a, **k):
    t0 = time.monotonic()
    r = _orig_solve(self, *a, **k)
    STAT["cpsat_t"] += time.monotonic() - t0
    STAT["cpsat_n"] += 1
    return r
cp_model.CpSolver.Solve = _solve

_orig_dec = M._decode_bay
def _dec(*a, **k):
    t0 = time.monotonic()
    r = _orig_dec(*a, **k)
    STAT["redecode_t"] += time.monotonic() - t0
    STAT["redecode_n"] += 1
    return r
M._decode_bay = _dec

if __name__ == "__main__":
    name = sys.argv[1]
    tl = float(sys.argv[sys.argv.index("--timelimit") + 1]) if "--timelimit" in sys.argv else 100.0
    prob = json.load(open(os.path.join(TRAIN, name + ".json"), encoding="utf-8"))
    t0 = time.monotonic()
    sol = M.algorithm(prob, tl)
    dt = time.monotonic() - t0
    feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
    print(f"\n==== PROFILE {name} tl={tl} ====", flush=True)
    print(f"z1={o1} obj={obj:.0f} wall={dt:.1f}s feas={bool(feas)}", flush=True)
    print(f"CP-SAT solve: {STAT['cpsat_t']:.1f}s over {STAT['cpsat_n']} calls "
          f"({STAT['cpsat_t']/max(1,STAT['cpsat_n']):.2f}s/call)", flush=True)
    print(f"re-decode   : {STAT['redecode_t']:.1f}s over {STAT['redecode_n']} calls "
          f"({STAT['redecode_t']/max(1,STAT['redecode_n']):.3f}s/call)", flush=True)
    print(f"other       : {dt - STAT['cpsat_t'] - STAT['redecode_t']:.1f}s", flush=True)
