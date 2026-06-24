"""Deep per-SOLUTION anatomy CLI for OGC2026.

Loads one instance + one solution, scores it with the official scorer, and
prints a structured breakdown of WHERE the objective comes from:
  - OBJECTIVE: weighted contribution + % share of each component (who dominates)
  - Z1 tardiness: top tardy blocks + whether their deadlines were intrinsically
    reachable (slack_intrinsic >= 0 => tardiness is induced by crane/packing)
  - Z2 imbalance: per-bay (weighted) loads + worst imbalance pair
  - Z3 preference: off-preference placements ranked by deviation
  - Packing headroom: bbox-reserved vs true polygon footprint per bay

ASCII-only output (Windows cp949 console).  Read-only: builds entirely on
tools/ogc_analysis.py and never touches the solver.

Usage:
    python tools/sol_report.py <instance_name> <solution.json> [--top N]
    e.g. python tools/sol_report.py prob_13 results/_z0_prob_13.json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ogc_analysis as A  # noqa: E402


def _f(x, nd=2):
    """Format a number with nd decimals, or 'n/a' for None."""
    if x is None:
        return "n/a"
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def _i(x):
    """Format an integer-ish value, or 'n/a' for None."""
    if x is None:
        return "n/a"
    try:
        return f"{int(round(float(x)))}"
    except (TypeError, ValueError):
        return str(x)


def _rule(ch="-", n=72):
    return ch * n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Per-solution objective anatomy for OGC2026.")
    ap.add_argument("instance", help="instance name or path, e.g. prob_13")
    ap.add_argument("solution", help="solution json path")
    ap.add_argument("--top", type=int, default=12,
                    help="how many tardy blocks to list (default 12)")
    args = ap.parse_args(argv)

    prob = A.load_instance(args.instance)
    sol = A.load_solution(args.solution)

    w = prob.get("weights", {})
    w1 = float(w.get("w1", 0))
    w2 = float(w.get("w2", 0))
    w3 = float(w.get("w3", 0))
    n_blocks = len(prob["blocks"])
    n_bays = len(prob["bays"])

    rep = A.score(prob, sol)
    feasible = bool(rep.get("feasible"))
    stage = rep.get("stage")

    # ---------------------------------------------------------------- HEADER
    print(_rule("="))
    print(f"SOLUTION REPORT  instance={prob.get('name', args.instance)}"
          f"  solution={os.path.basename(args.solution)}")
    print(_rule("="))
    print(f"blocks={n_blocks}  bays={n_bays}  "
          f"weights: w1={_i(w1)} w2={_i(w2)} w3={_i(w3)}")
    if feasible:
        print("feasibility: FEASIBLE")
    else:
        print(f"feasibility: INFEASIBLE  (failed at stage {stage})")
        viol = rep.get("violations")
        if viol:
            print(f"violations: {viol}")
        print(_rule("="))
        return 0

    # ------------------------------------------------------------- OBJECTIVE
    obj = float(rep.get("objective", 0.0))
    o1 = float(rep.get("obj1", 0.0))
    o2 = float(rep.get("obj2", 0.0))
    o3 = float(rep.get("obj3", 0.0))
    c1, c2, c3 = w1 * o1, w2 * o2, w3 * o3
    tot = c1 + c2 + c3
    if tot <= 0:
        tot = 1.0  # avoid div0; all-zero objective

    print()
    print("OBJECTIVE")
    print(_rule())
    print(f"  objective (weighted total) = {_f(obj)}")
    print(f"  {'component':<12}{'raw':>12}{'weight':>10}"
          f"{'weighted':>14}{'share':>9}")
    print(f"  {'-'*12}{'-'*12:>12}{'-'*10:>10}{'-'*14:>14}{'-'*9:>9}")
    for name, raw, wt, contrib in (("obj1 (Z1)", o1, w1, c1),
                                    ("obj2 (Z2)", o2, w2, c2),
                                    ("obj3 (Z3)", o3, w3, c3)):
        share = 100.0 * contrib / tot
        print(f"  {name:<12}{_f(raw):>12}{_i(wt):>10}"
              f"{_f(contrib):>14}{_f(share, 1) + '%':>9}")
    dominant = max((("obj1", c1), ("obj2", c2), ("obj3", c3)),
                   key=lambda t: t[1])[0]
    print(f"  -> dominant component: {dominant} "
          f"({_f(100.0 * max(c1, c2, c3) / tot, 1)}% of total)")

    # ----------------------------------------------------------- Z1 TARDINESS
    pt = A.per_block_tardiness(prob, sol)
    tardy_rows = [r for r in pt if r["tardy"] is not None and r["tardy"] > 0]
    n_tardy = len(tardy_rows)
    induced = sum(1 for r in tardy_rows if r["slack_intrinsic"] >= 0)

    print()
    print("Z1 TARDINESS")
    print(_rule())
    print(f"  tardy blocks = {n_tardy}  (obj1 sum = {_f(o1)})")
    if tardy_rows:
        print(f"  {'block':>6}{'bay':>5}{'entry':>8}{'exit':>8}"
              f"{'due':>8}{'tardy':>8}{'slk_intr':>10}")
        print(f"  {'-'*6:>6}{'-'*5:>5}{'-'*8:>8}{'-'*8:>8}"
              f"{'-'*8:>8}{'-'*8:>8}{'-'*10:>10}")
        for r in tardy_rows[:args.top]:
            print(f"  {_i(r['block']):>6}{_i(r['bay']):>5}"
                  f"{_f(r['entry'], 1):>8}{_f(r['exit'], 1):>8}"
                  f"{_f(r['due'], 1):>8}{_f(r['tardy'], 1):>8}"
                  f"{_i(r['slack_intrinsic']):>10}")
        if n_tardy > args.top:
            print(f"  ... {n_tardy - args.top} more tardy blocks not shown")
        print(f"  note: {induced}/{n_tardy} tardy blocks have "
              f"slack_intrinsic >= 0")
        print("        => their deadlines were reachable; tardiness is induced "
              "by crane")
        print("        serialization / packing, not impossible deadlines.")
    else:
        print("  no tardy blocks.")

    # ----------------------------------------------------------- Z2 IMBALANCE
    bl = A.bay_loads(prob, sol)
    loads = bl["loads"]
    u = bl["u"]
    weighted = bl["weighted"]
    wj, wk = bl["worst_pair"]

    print()
    print("Z2 IMBALANCE")
    print(_rule())
    print(f"  {'bay':>5}{'load':>12}{'u_j':>10}{'weighted':>14}")
    print(f"  {'-'*5:>5}{'-'*12:>12}{'-'*10:>10}{'-'*14:>14}")
    for j in range(len(loads)):
        mark = "  <-" if j in (wj, wk) else ""
        print(f"  {j:>5}{_f(loads[j]):>12}{_f(u[j], 3):>10}"
              f"{_f(weighted[j]):>14}{mark}")
    print(f"  worst pair: bay {wj} vs bay {wk}  "
          f"gap={_f(bl['worst_gap'])}  obj2=floor(gap)={_i(bl['obj2'])}")

    # ----------------------------------------------------------- Z3 PREFERENCE
    pd = A.pref_deviations(prob, sol)
    off = pd["off"]

    print()
    print("Z3 PREFERENCE")
    print(_rule())
    print(f"  obj3 (sum deviation) = {_f(pd['obj3'])}  "
          f"off-preference placements = {pd['n_off']}")
    if off:
        print(f"  top {min(8, len(off))} by deviation:")
        print(f"  {'block':>6}{'bay':>5}{'dev':>8}")
        print(f"  {'-'*6:>6}{'-'*5:>5}{'-'*8:>8}")
        for r in off[:8]:
            print(f"  {_i(r['block']):>6}{_i(r['bay']):>5}{_f(r['dev'], 1):>8}")
    else:
        print("  all blocks on their preferred bay.")

    # ------------------------------------------------------ PACKING HEADROOM
    fr = A.bbox_fragmentation(prob, sol)
    print()
    print("PACKING HEADROOM  (bbox reserved vs true polygon footprint)")
    print(_rule())
    print(f"  {'bay':>5}{'poly':>12}{'bbox':>12}{'bay_area':>12}"
          f"{'waste%bay':>11}")
    print(f"  {'-'*5:>5}{'-'*12:>12}{'-'*12:>12}{'-'*12:>12}{'-'*11:>11}")
    HIGH = 30.0  # waste_pct_of_bay threshold to flag
    flagged = []
    for b in fr["per_bay"]:
        wp = b["waste_pct_of_bay"]
        flag = "  *HIGH" if wp >= HIGH else ""
        if wp >= HIGH:
            flagged.append(b["bay"])
        print(f"  {_i(b['bay']):>5}{_f(b['poly'], 1):>12}"
              f"{_f(b['bbox'], 1):>12}{_f(b['bay_area'], 1):>12}"
              f"{_f(wp, 1) + '%':>11}{flag}")
    if flagged:
        print(f"  flagged bays (waste >= {_i(HIGH)}% of bay): {flagged}")
        print("  => bbox packer is reserving space exact-polygon packing could "
              "recover.")
    else:
        print(f"  no bay above {_i(HIGH)}% bbox waste.")

    print(_rule("="))
    return 0


if __name__ == "__main__":
    sys.exit(main())
