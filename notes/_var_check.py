"""Variance + current-default check at a given tl.
Runs each instance N times (default config) and prints z1/obj per run.
Usage: python notes/_var_check.py prob_20:3,prob_14:2 --timelimit 100
"""
import json, time, sys, os
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "instances", "train")

def parse(spec):
    out = []
    for tok in spec.split(","):
        if ":" in tok:
            name, n = tok.split(":"); out.append((name, int(n)))
        else:
            out.append((tok, 1))
    return out

if __name__ == "__main__":
    spec = sys.argv[1]
    tl = float(sys.argv[sys.argv.index("--timelimit") + 1]) if "--timelimit" in sys.argv else 100.0
    for name, n in parse(spec):
        path = os.path.join(TRAIN, name + ".json")
        prob = json.load(open(path, encoding="utf-8"))
        zs = []
        for r in range(n):
            t0 = time.monotonic()
            sol = algorithm(prob, tl)
            dt = time.monotonic() - t0
            feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
            zs.append((o1, obj))
            print(f"{name} run{r+1}/{n}: z1={o1} obj={obj:.0f} wall={dt:.1f}s feas={bool(feas)}", flush=True)
        z1s = [z for z, _ in zs]
        print(f"  >> {name} z1 min={min(z1s)} max={max(z1s)} (n={n})", flush=True)
