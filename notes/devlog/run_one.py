"""Single-instance dev runner (mirrors the capture driver, one instance).

  python notes/devlog/run_one.py prob_1 --timelimit 30 --env OGC_REBUILD=1,OGC_W1=1

Prints the met dict (feas/z1/z2/z3/obj/wall) to stdout; the solver's
[REBUILD_SEQ]/[STAGE_*] traces go to stderr.  For fast iteration only — adoption
judgments still use notes/_capture20_aff.py full-20 paired.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
TRAIN = ROOT / "instances" / "train"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inst")
    ap.add_argument("--timelimit", type=float, default=30.0)
    ap.add_argument("--env", default="")
    a = ap.parse_args()
    for kv in a.env.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            os.environ[k.strip()] = v.strip()
    sys.path.insert(0, str(TOOLS))
    sys.path.insert(0, str(SRC))
    import ogc_analysis as A
    sys.path.insert(0, str(SRC))
    from myalgorithm import algorithm
    prob = json.load(open(TRAIN / f"{a.inst}.json", encoding="utf-8"))
    t0 = time.monotonic()
    sol = algorithm(prob, a.timelimit)
    dt = time.monotonic() - t0
    feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
    met = {"inst": a.inst, "wall": round(dt, 2), "feas": bool(feas),
           "z1": o1, "z2": o2, "z3": o3, "obj": obj}
    print(json.dumps(met))


if __name__ == "__main__":
    main()
