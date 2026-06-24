"""H15: re-time box's FIXED layout with the LEGACY per-bay CP-SAT timing oracle (+ my
connected-component decomposition). box's packer does its own timing; the legacy oracle may
find a better crane-feasible serialization on the SAME positions ⇒ lower z1 (helps the z1-OVER
losses). Does NOT change z3 (positions/assignment fixed). Cross-applies legacy timing to box.

Usage: python notes/research/_retime.py <inst> [tl]
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ["OGC_TIMING_DECOMP"] = "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M  # noqa
from myalgorithm import (_results_from_solution, _cpsat_bay_timing_verified,  # noqa
                         check_feasibility)
from utils import Bay  # noqa

COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                      encoding="utf-8"))["competitor"]


def run(inst, tl=60.0):
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json", encoding="utf-8"))
    cap = json.load(open(ROOT / "results" / "capture" / "box120_set2" / f"{inst}.json",
                         encoding="utf-8"))
    sol = cap["solution"]
    m0 = cap["met"]
    bays = [Bay.from_dict(b, i) for i, b in enumerate(prob["bays"])]
    _a, results, _f = _results_from_solution(prob, sol)
    c = COMP[inst]
    t0 = time.monotonic()
    sol2 = _cpsat_bay_timing_verified(prob, bays, results, deadline=t0 + tl, lb_skip=False)
    dt = time.monotonic() - t0
    if sol2 is None:
        print(f"{inst}: re-time no improvement (dt={dt:.0f}s)  "
              f"box z1={m0['z1']:.0f} z3={m0['z3']:.0f} obj={m0['obj']:,.0f} | comp obj={c['obj']:,.0f}")
        return
    ck = check_feasibility(prob, sol2)
    print(f"{inst}: box(z1={m0['z1']:.0f},z3={m0['z3']:.0f},obj={m0['obj']:,.0f}) -> "
          f"retimed(z1={ck.get('obj1'):.0f},z3={ck.get('obj3'):.0f},obj={ck.get('objective'):,.0f}) "
          f"[dt={dt:.0f}s] | comp(obj={c['obj']:,.0f}) "
          f"{'obj<comp' if ck.get('objective', 9e18) < c['obj'] else ''}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "prob_38",
        float(sys.argv[2]) if len(sys.argv) > 2 else 60.0)
