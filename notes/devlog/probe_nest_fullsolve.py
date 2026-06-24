"""Full-solve objective gate for OGC_UC_NEST (LCA placer) vs baseline (BL).

Per user directive (2026-06-14): judge by TOTAL objective, not z-components.
Runs the real submit-path algorithm() on the flip-target losses with NEST OFF
then ON, prints obj/z1/z2/z3 and the per-instance delta + competitor gap.

  conda run -n ogc2025 python notes/devlog/probe_nest_fullsolve.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as A          # noqa: E402
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M            # noqa: E402  (OGC_UC_NEST is read LIVE in uconstruct)

COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-11.json",
                      encoding="utf-8"))["competitor"]
INSTS = sys.argv[1:] or ["prob_11", "prob_17", "prob_3"]
TL = float(os.environ.get("NEST_TL", "120"))


def run(inst, nest):
    os.environ["OGC_UC_NEST"] = "1" if nest else "0"
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json",
                         encoding="utf-8"))
    t0 = time.monotonic()
    sol = M.algorithm(prob, TL)
    dt = time.monotonic() - t0
    feas, obj, z1, z2, z3 = A.obj_tuple(prob, sol)
    return dict(feas=bool(feas), obj=obj, z1=z1, z2=z2, z3=z3, wall=round(dt, 1))


print(f"NEST full-solve gate  TL={TL}s")
print(f"{'inst':<9}{'mode':<5}{'obj':>11}{'z1':>5}{'z2':>8}{'z3':>8}{'wall':>6}"
      f"{'comp':>9}{'vs_comp':>9}{'d_obj':>9}  beats?")
print("-" * 92)
for inst in INSTS:
    off = run(inst, False)
    on = run(inst, True)
    c = COMP[inst]["obj"]
    for mode, r in (("OFF", off), ("ON", on)):
        vs = f"{(r['obj']-c)/c*100:+.0f}%"
        dobj = "" if mode == "OFF" else f"{r['obj']-off['obj']:+.0f}"
        beats = "WIN" if (r["feas"] and r["obj"] < c) else ""
        print(f"{inst:<9}{mode:<5}{r['obj']:>11.0f}{r['z1']:>5.0f}{r['z2']:>8.1f}"
              f"{r['z3']:>8.0f}{r['wall']:>6.0f}{c:>9.0f}{vs:>9}{dobj:>9}  {beats}")
    print("-" * 92)
