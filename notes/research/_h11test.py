"""H11 lever test: does accurate-z1 (cells) Phase B unlock z3-reducing moves that the
bbox proxy rejects? Calls boxsolver._solve_reassign DIRECTLY (in-process, no spawn pool)
with OGC_ACCZ1 off vs on. Flushed output. Run from a real file (spawn-safe).

  FS_TL=80 python notes/research/_h11test.py prob_13 prob_14 prob_20
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as OA                      # noqa: E402
sys.path.insert(0, str(ROOT / "src"))
import boxsolver as BS                         # noqa: E402
from utils import Bay                          # noqa: E402


def main():
    TL = float(os.environ.get("FS_TL", "80"))
    targets = sys.argv[1:] or ["prob_13"]
    COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                          encoding="utf-8"))["competitor"]
    HYB = json.load(open(ROOT / "notes" / "research" / "baselines" / "hybrid_set1.json"))
    os.environ["OGC_PHASEB"] = "0"             # ACCZ1 implies Phase B internally
    print(f"H11 test  FS_TL={TL}  (_solve_reassign direct, ACCZ1 off vs on)", flush=True)
    for name in targets:
        prob = json.load(open(ROOT / "instances" / "train" / f"{name}.json", encoding="utf-8"))
        blocks = prob["blocks"]; bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
        hy = HYB.get(name, {}); cm = COMP.get(name, {})
        print(f"\n{name}: hybrid obj={hy.get('obj')} z3={hy.get('z3')} | "
              f"comp obj={cm.get('obj')} z2={cm.get('z2')} z3={cm.get('z3')}", flush=True)
        runs = [("reassign", BS._solve_reassign), ("feasspill", BS._solve_feasspill)]
        for tag, fn in runs:
            BS._FP_CACHE.clear()
            t0 = time.monotonic()
            try:
                r = fn(prob, blocks, bays, t0 + TL)
            except Exception as e:
                print(f"  {tag:<10}: ERR {type(e).__name__}: {str(e)[:70]}", flush=True)
                continue
            dt = time.monotonic() - t0
            if r is None:
                print(f"  {tag:<10}: None  wall={dt:.1f}", flush=True)
                continue
            obj, sol = r
            feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
            print(f"  {tag:<10}: obj={o:.0f} z1={z1:.0f} z2={z2:.0f} z3={z3:.0f} "
                  f"wall={dt:.1f} feas={feas}", flush=True)


if __name__ == "__main__":
    main()
