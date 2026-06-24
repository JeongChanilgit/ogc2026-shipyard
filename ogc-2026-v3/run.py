"""
run.py -- CLI driver for the block coordinate-descent CP-SAT polish.

Usage:
    python run.py [prob=prob_29] [total_time_s=30]

Builds a full per-bay greedy seed, evaluates it (BEFORE), runs the full-obj
gated coordinate-descent polish, and evaluates the result (AFTER).  The polish
is provably never-worse than the seed, so AFTER.obj <= BEFORE.obj always.
"""
from __future__ import annotations

import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)


def _find_inst(prob_name: str) -> str | None:
    if os.path.isfile(prob_name):
        return prob_name
    for rel in [
        "../instances/train",
        "../../instances/train",
        "instances/train",
        os.path.join(THIS, "..", "instances", "train"),
        os.path.join(THIS, "..", "..", "instances", "train"),
    ]:
        p = os.path.normpath(os.path.join(THIS, rel, prob_name + ".json"))
        if os.path.isfile(p):
            return p
        p2 = os.path.normpath(os.path.join(THIS, rel, prob_name))
        if os.path.isfile(p2):
            return p2
    return None


def _fmt(ev: dict) -> str:
    def _n(v):
        return f"{v:.2f}" if isinstance(v, float) else str(v)
    return (f"obj={_n(ev['obj'])} z1={_n(ev['z1'])} z2={_n(ev['z2'])} "
            f"z3={_n(ev['z3'])} feasible={ev['feasible']}")


def main():
    from seed import make_seed, global_eval
    from coorddesc import coorddesc

    args = sys.argv[1:]
    prob = args[0] if len(args) > 0 else "prob_29"
    total_time_s = float(args[1]) if len(args) > 1 else 30.0

    inst = _find_inst(prob)
    if inst is None:
        print(f"Instance not found: {prob}", file=sys.stderr)
        sys.exit(1)

    t0 = time.monotonic()

    bays_placed, data = make_seed(inst, scale=2)
    n_bays = len([j for j in bays_placed if bays_placed[j]])
    n_blocks = sum(len(v) for v in bays_placed.values())

    before = global_eval(data, bays_placed)

    best, log = coorddesc(data, bays_placed, inst,
                          total_time_s=total_time_s, scale=2)
    after = global_eval(data, best)

    wall = time.monotonic() - t0

    # accepted-moves summary by axis
    acc_by_axis: dict[str, int] = {}
    n_acc = 0
    for row in log:
        if row.get("accepted"):
            ax = row.get("axis", "?")
            acc_by_axis[ax] = acc_by_axis.get(ax, 0) + 1
            n_acc += 1
    acc_summary = ", ".join(f"{k}={acc_by_axis.get(k, 0)}"
                            for k in ("x", "y", "t")) + f"  (total {n_acc})"

    bo = before["obj"]
    ao = after["obj"]
    delta = (ao - bo) if (bo is not None and ao is not None) else None
    delta_pct = (delta / bo * 100.0) if (delta is not None and bo) else None

    print(f"\n{'='*64}")
    print(f"Instance : {os.path.basename(inst)}")
    print(f"#bays    : {n_bays}    #blocks : {n_blocks}")
    print(f"{'='*64}")
    print(f"BEFORE : {_fmt(before)}")
    print(f"accepted moves: {acc_summary}")
    print(f"AFTER  : {_fmt(after)}")
    if delta is not None:
        dp = f"{delta_pct:+.3f}%" if delta_pct is not None else "n/a"
        print(f"delta  : {delta:+.2f} ({dp})")
    else:
        print(f"delta  : n/a")
    print(f"wall   : {wall:.1f}s")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
