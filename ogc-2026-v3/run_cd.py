"""run_cd.py -- PER-AXIS alternating coordinate-descent crane-repack driver.

Unlike run_squeeze.py (one monolithic crane_repack_bay call mixing x/y/o/timing
in a single CP-SAT model), this driver solves ONE AXIS AT A TIME -- timing, x,
y, o -- as SEPARATE single-axis passes, alternating, exactly like the per-bay
timing oracle was originally meant to. Each pass freezes the other axes and lets
CP-SAT optimise only the chosen axis (+ entry times, which every pass already
re-solves jointly).

Axis -> crane_repack_bay candidate kwargs:
    't' (timing) -> n_xcand=0, n_ycand=0, n_ocand=0  (positions FROZEN, candidate
                    0 only => the model optimises ONLY entry times = the pure
                    timing oracle)
    'x'          -> n_xcand=K, n_ycand=0, n_ocand=0  (x-anchors + entry)
    'y'          -> n_xcand=0, n_ycand=K, n_ocand=0  (y-anchors + entry)
    'o'          -> n_xcand=0, n_ycand=0, n_ocand=K  (orient-variants + entry)

For each round we walk every tardy bay (z1 > 0, worst first) and, within a bay,
cycle the axes in `order` (default "txyo"). Each pass is gated by the OFFICIAL
full-solution checker (seed.global_eval): accept iff feasible AND obj strictly
improves. A round that accepts nothing => converged.

Usage: python run_cd.py [prob=prob_38] [total_time_s=600] [K=5] [order=txyo]
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter          # noqa: E402
import seed as S        # noqa: E402
import crane_cpsat as C # noqa: E402


# axis letter -> (n_xcand, n_ycand, n_ocand) factory given K.
def _axis_kwargs(axis: str, K: int):
    if axis == "t":
        return (0, 0, 0)        # timing only -- positions frozen
    if axis == "x":
        return (K, 0, 0)        # x-anchors + entry
    if axis == "y":
        return (0, K, 0)        # y-anchors + entry
    if axis == "o":
        return (0, 0, K)        # orient-variants + entry
    raise ValueError(f"unknown axis '{axis}' (expected one of t/x/y/o)")


def _bz1(data, pl):
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in pl)


def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    K = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    order = sys.argv[4] if len(sys.argv) > 4 else "txyo"

    bad = [c for c in order if c not in "txyo"]
    if bad or not order:
        print(f"bad order '{order}' -- letters must be a subset of t/x/y/o", flush=True)
        return

    data = json.load(open(os.path.join("..", "instances", "train", prob + ".json"),
                          encoding="utf-8"))
    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"real_{prob}.json")
    if not os.path.isfile(real):
        print(f"missing {real}", flush=True)
        return
    sol = json.load(open(real, encoding="utf-8"))
    cur = adapter.deserialize(data, sol)
    base = S.global_eval(data, cur)
    cur_obj = base["obj"]

    print(f"=== {prob} COORD-DESCENT  (TL={tl:.0f}s K={K} order={order}) ===", flush=True)
    print(f"BEFORE obj={base['obj']} z1={base['z1']} z2={base['z2']} z3={base['z3']} "
          f"feas={base['feasible']}", flush=True)
    if not base["feasible"]:
        print("infeasible -- abort", flush=True)
        return

    # per-axis ACCEPT accounting (which axes actually carry the gains).
    acc = {a: {"n": 0, "obj_gain": 0.0} for a in order}

    t0 = time.monotonic()
    deadline = t0 + tl
    rnd = 0
    while time.monotonic() < deadline - 1.0:
        rnd += 1
        bays_t = [(j, _bz1(data, pl)) for j, pl in cur.items()]
        bays_t = [(j, z) for j, z in bays_t if z > 0]
        bays_t.sort(key=lambda x: -x[1])
        if not bays_t:
            print(f"round {rnd}: no tardy bay -- done", flush=True)
            break
        n_tardy = len(bays_t)
        improved = False
        for j, z1 in bays_t:
            for axis in order:
                now = time.monotonic()
                if now >= deadline - 1.0:
                    break
                remain = deadline - now
                # per-pass slice: split the remaining budget evenly across the
                # (tardy-bay x axis) cells still to come this round, floored at
                # 15s and capped by what's left.
                # CP-SAT plateaus ~10s on the biggest bay (measured), so cap the
                # per-pass slice: same obj, far less wall => more rounds fit.
                _cap = float(os.environ.get("OGC_PASS_CAP", "1e9"))
                per = min(remain, max(10.0, min(remain / (n_tardy * len(order)), _cap)))
                nxc, nyc, noc = _axis_kwargs(axis, K)
                z1_before = _bz1(data, cur[j])
                try:
                    new_pl, st, wall, info = C.crane_repack_bay(
                        data, j, cur[j], per, n_xcand=nxc, n_ycand=nyc, n_ocand=noc)
                except TypeError:
                    new_pl, st, wall, info = C.crane_repack_bay(
                        data, j, cur[j], per, n_xcand=nxc, n_ycand=nyc)
                if new_pl is None:
                    print(f"  r{rnd} bay{j} {axis} z1={int(z1_before)} no-sol ({st})",
                          flush=True)
                    continue
                trial = dict(cur)
                trial[j] = new_pl
                ev = S.global_eval(data, trial)
                z1_after = _bz1(data, new_pl)
                accepted = ev["feasible"] and ev["obj"] < cur_obj - 1e-6
                if accepted:
                    gain = cur_obj - ev["obj"]
                    cur = trial
                    cur_obj = ev["obj"]
                    improved = True
                    acc[axis]["n"] += 1
                    acc[axis]["obj_gain"] += gain
                    print(f"  r{rnd} bay{j} {axis} z1={int(z1_before)}->{int(z1_after)} "
                          f"ACCEPT obj->{ev['obj']:.0f} ({wall:.0f}s {st})", flush=True)
                else:
                    print(f"  r{rnd} bay{j} {axis} z1={int(z1_before)}->{int(z1_after)} "
                          f"reject obj={ev['obj']:.0f} feas={ev['feasible']} "
                          f"({wall:.0f}s {st})", flush=True)
            if time.monotonic() >= deadline - 1.0:
                break
        if not improved:
            print(f"round {rnd}: no improvement -- converged", flush=True)
            break

    after = S.global_eval(data, cur)
    d = after["obj"] - base["obj"]
    print(f"AFTER  obj={after['obj']} z1={after['z1']} z2={after['z2']} z3={after['z3']} "
          f"feas={after['feasible']}", flush=True)
    print(f"delta  {d:+.0f} ({d / base['obj'] * 100:+.2f}%)  rounds={rnd} "
          f"wall={time.monotonic() - t0:.0f}s", flush=True)
    print("per-axis ACCEPTs:", flush=True)
    for a in order:
        print(f"  '{a}': {acc[a]['n']} accepts, obj_gain={acc[a]['obj_gain']:+.0f}",
              flush=True)


if __name__ == "__main__":
    main()
