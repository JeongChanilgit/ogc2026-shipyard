"""run_b.py -- tester for the cross-bay reassignment pass (bpass.py).

Loads an instance + its real_<prob>.json solution, deserializes it into per-bay
placed lists, prints the BEFORE objective, counts tardy+wrong-bay targets, runs
`bpass` (full-obj never-worse gate), and prints the AFTER objective + per-move
accept/reject summary.  AFTER.obj <= BEFORE.obj always (provable).

Usage: python run_b.py [prob=prob_38] [total_time_s=120]
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

import adapter            # noqa: E402
from seed import global_eval  # noqa: E402
from bpass import bpass, _preferred  # noqa: E402


def _find_inst(prob):
    if os.path.isfile(prob):
        return prob
    for rel in ["../instances/train", "../../instances/train", "instances/train"]:
        p = os.path.normpath(os.path.join(THIS, rel, prob + ".json"))
        if os.path.isfile(p):
            return p
    return None


def _fmt(ev):
    def _n(v):
        return f"{v:.2f}" if isinstance(v, float) else str(v)
    return (f"obj={_n(ev['obj'])} z1={_n(ev['z1'])} z2={_n(ev['z2'])} "
            f"z3={_n(ev['z3'])} feasible={ev['feasible']}")


def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    total_time_s = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0

    inst = _find_inst(prob)
    if inst is None:
        print(f"Instance not found: {prob}", file=sys.stderr)
        sys.exit(1)
    real = os.path.join(THIS, f"real_{prob}.json")
    if not os.path.isfile(real):
        print(f"missing {real}", file=sys.stderr)
        sys.exit(1)

    data = json.load(open(inst, encoding="utf-8"))
    sol = json.load(open(real, encoding="utf-8"))
    cur = adapter.deserialize(data, sol)

    before = global_eval(data, cur)

    # count tardy & wrong-bay targets
    n_targets = 0
    for j, placed in cur.items():
        for p in placed:
            bid = p["id"]
            due = data["blocks"][bid].get("due_date", 0)
            if p["exit"] > due and _preferred(data, bid) != j:
                n_targets += 1

    print(f"\n{'='*64}", flush=True)
    print(f"Instance : {os.path.basename(inst)}   (total_time_s={total_time_s:.0f})",
          flush=True)
    n_bays = len([j for j in cur if cur[j]])
    n_blocks = sum(len(v) for v in cur.values())
    print(f"#bays    : {n_bays}    #blocks : {n_blocks}", flush=True)
    print(f"BEFORE   : {_fmt(before)}", flush=True)
    print(f"targets  : {n_targets} tardy & wrong-bay blocks", flush=True)
    print(f"{'='*64}", flush=True)

    t0 = time.monotonic()
    best, log = bpass(data, cur, total_time_s=total_time_s)
    wall = time.monotonic() - t0

    after = global_eval(data, best)

    print(f"\n{'='*64}", flush=True)
    print(f"MOVE SUMMARY  (n_targets={log['n_targets']})", flush=True)
    print(f"  accepted            : {log['accepted']}", flush=True)
    print(f"  rejected infeasible : {log['rejected_infeasible']}", flush=True)
    print(f"  rejected noimprove  : {log['rejected_noimprove']}", flush=True)
    print(f"  no-move/skip        : {log['no_move']}", flush=True)
    # show accepted moves
    for m in log["moves"]:
        if m.get("accepted"):
            print(f"    ACCEPT block {m['id']}  bay {m['from_bay']}->{m['to_bay']}  "
                  f"obj_delta={m.get('obj_delta', 0.0):+.2f}  z3c={m.get('z3c')}",
                  flush=True)

    bo, ao = before["obj"], after["obj"]
    delta = ao - bo if (bo is not None and ao is not None) else None
    dpct = (delta / bo * 100.0) if (delta is not None and bo) else None

    z3_red = (before["z3"] - after["z3"]) if (
        before["z3"] is not None and after["z3"] is not None) else None
    z1_delta = (after["z1"] - before["z1"]) if (
        before["z1"] is not None and after["z1"] is not None) else None

    print(f"\nBEFORE : {_fmt(before)}", flush=True)
    print(f"AFTER  : {_fmt(after)}", flush=True)
    if delta is not None:
        dp = f"{dpct:+.4f}%" if dpct is not None else "n/a"
        print(f"delta  : obj {delta:+.2f} ({dp})", flush=True)
    print(f"  z3 reduction : {z3_red}", flush=True)
    print(f"  z1 delta     : {z1_delta:+}" if z1_delta is not None
          else "  z1 delta     : n/a", flush=True)
    print(f"  accepted moves: {log['accepted']} / {log['n_targets']} targets",
          flush=True)
    print(f"  wall : {wall:.1f}s", flush=True)
    # sanity: never-worse
    if delta is not None:
        assert ao <= bo + 1e-6, f"NEVER-WORSE VIOLATED: {bo} -> {ao}"
        print(f"  [gate] never-worse OK (AFTER.obj <= BEFORE.obj)", flush=True)
    print(f"{'='*64}", flush=True)


if __name__ == "__main__":
    main()
