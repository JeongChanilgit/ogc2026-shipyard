"""
myalgorithm.py -- all-CP-SAT solver entry point.

    algorithm(prob_info, timelimit) -> {"operations": {...}}

Every decision (bay assignment, x, y, orientation, entry/exit time) is made by a
CP-SAT solve.  The architecture is a logic-based Benders decomposition (LBBD):

    master_cp.py    CP-SAT: bay assignment + relaxed schedule (w1Z1+w2Z2+w3Z3)
        |  no-good / cardinality cuts
    bay_pack_cp.py  CP-SAT: per-bay (orient, x, y, entry, exit) with the EXACT
                    crane j>=k rule and same-layer collision, min tardiness
    solver.py       drives the loop, keeps the best grader-verified solution

A serial-per-bay layout is the only non-CP-SAT path; it exists purely as a
feasibility floor so the solver never returns -1.

CLI:  python myalgorithm.py <instance.json> [timelimit]
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import solver  # noqa: E402


def algorithm(prob_info: dict, timelimit: float) -> dict:
    verbose = bool(os.environ.get("OGC_CPSAT_VERBOSE"))
    try:
        return solver.lbbd_solve(prob_info, float(timelimit), verbose=verbose)
    except Exception:  # never crash the grader: fall back to the feasibility floor
        if verbose:
            import traceback
            traceback.print_exc()
        import data
        prob = data.parse(prob_info)
        return solver.place_to_ops(solver.serial_floor(prob))


# -----------------------------------------------------------------------------
# Local test harness
# -----------------------------------------------------------------------------
def _main():
    import json
    import time

    if len(sys.argv) < 2:
        print("usage: python myalgorithm.py <instance.json> [timelimit]")
        return
    path = sys.argv[1]
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    os.environ.setdefault("OGC_CPSAT_VERBOSE", "1")

    with open(path, "r", encoding="utf-8") as f:
        prob_info = json.load(f)

    t0 = time.monotonic()
    sol = algorithm(prob_info, tl)
    elapsed = time.monotonic() - t0

    import utils
    res = utils.check_feasibility(prob_info, sol)
    print(f"\n=== {os.path.basename(path)} ===")
    print(f"blocks={len(prob_info['blocks'])} bays={len(prob_info['bays'])} "
          f"weights={prob_info.get('weights')}")
    print(f"wall={elapsed:.1f}s feasible={res.get('feasible')} stage={res.get('stage')}")
    print(f"objective={res.get('objective')} "
          f"z1={res.get('obj1')} z2={res.get('obj2')} z3={res.get('obj3')}")
    if not res.get("feasible"):
        print("violations:", res.get("violations")[:5])


if __name__ == "__main__":
    _main()
