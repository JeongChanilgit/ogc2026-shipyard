"""Realizability-aware assignment diagnostic (structural angle, 2026-06-14 PM).

Question: is our z3 high because (a) the CP-SAT area-cap spreads blocks too much
(assignment z3 already high), or (b) a low-z3 assignment exists but we can't
REALIZE it at z1=0 (spill inflates z3)?

For each area-cap alpha, build the CP-SAT (z2+z3-optimal) assignment, report its
CLOSED-FORM z3 (pref deviation on the bay map, decode-independent), then REALIZE
it (per-bay crane-safe decode at entry=R + the global timing oracle) and report
the realizable z1.  The loosest alpha that realizes z1~0 with z3 BELOW our current
realized z3 == z3 we are leaving on the table (cap too tight) == structural win.

  conda run -n ogc2025 python notes/devlog/probe_assign_realize.py prob_3 prob_11 prob_17
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M          # noqa: E402
import uconstruct as UC          # noqa: E402
from utils import Bay            # noqa: E402
os.environ["OGC_UC_NEST"] = "0"

COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-11.json",
                      encoding="utf-8"))["competitor"]


def bays_u(p):
    bays = [Bay.from_dict(d, i) for i, d in enumerate(p["bays"])]
    nb = len(bays)
    ar = [p["bays"][j]["width"] * p["bays"][j]["height"] for j in range(nb)]
    avg = sum(ar) / nb
    return bays, [avg / a for a in ar]


def closed_z3(prob, assign):
    bl = prob["blocks"]
    return sum(max(bl[b]["bay_preferences"]) - bl[b]["bay_preferences"][assign[b]]
               for b in range(len(bl)))


def realize_z1(prob, bays, bay_u, assign, deadline):
    """Per-bay entry=R crane-safe decode, then the global timing oracle.
    Returns realizable total z1 (and whether every bay decoded)."""
    nb = len(bays)
    blocks = prob["blocks"]
    members = {j: [b for b in range(len(blocks)) if assign[b] == j] for j in range(nb)}
    results = {}
    for j in range(nb):
        if not members[j]:
            continue
        recs, _ = UC._decode_bay(bays[j], j, members[j], blocks, deadline)
        if recs is None or len(recs) != len(members[j]):
            return None, False
        results[j] = recs
    try:
        imp = M._cpsat_bay_timing_verified(prob, bays, results, deadline=deadline)
    except Exception:
        imp = None
    if imp is not None:
        z1 = sum(max(0.0, int(t) - int(blocks[op["block_id"]]["due_date"]))
                 for t, ops in imp["operations"].items()
                 for op in ops if op.get("type") != "ENTRY")
        return z1, True
    # oracle skipped -> raw decode z1
    z1 = sum(max(0.0, int(a["exit_time"]) - int(blocks[b]["due_date"]))
             for j in results for b, a in results[j].items())
    return z1, True


def probe(inst):
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json",
                          encoding="utf-8"))
    bl = prob["blocks"]
    bays, bu = bays_u(prob)
    nb = len(bays)
    feas = M._feasible_bays(bl, bays)
    feas = [(f if f else list(range(nb))) for f in feas]
    c = COMP[inst]["obj"]
    w = prob.get("weights", {})
    w1 = float(w.get("w1", 1)); w2 = float(w.get("w2", 1)); w3 = float(w.get("w3", 1))
    print(f"\n=== {inst}  n={len(bl)} bays={nb}  w1={w1:.0f} w2={w2:.0f} w3={w3:.0f}"
          f"  comp_obj={c} ===")
    print(f"{'alpha':>7}{'z3':>8}{'w3*z3':>10}{'realized_z1':>12}{'note':>8}")
    # alpha None == no cap (CP-SAT free to pile preferred bays); tighter = spread.
    for alpha in [None, 1.3, 1.1, 1.0, 0.9, 0.85]:
        assign = M._cpsat_assignment(prob, bays, feas, bu, time_budget=8.0,
                                     cap_alpha=alpha)
        if assign is None:
            print(f"{str(alpha):>7}  (assignment None)")
            continue
        z3 = closed_z3(prob, assign)
        z1, ok = realize_z1(prob, bays, bu, assign, time.monotonic() + 25)
        z1s = f"{z1:.0f}" if z1 is not None else "FAIL"
        note = "z1~0" if (z1 is not None and z1 < 1e-6) else ""
        print(f"{str(alpha):>7}{z3:>8.0f}{w3*z3:>10.0f}{z1s:>12}{note:>8}")


if __name__ == "__main__":
    for inst in (sys.argv[1:] or ["prob_3", "prob_11", "prob_17"]):
        probe(inst)
