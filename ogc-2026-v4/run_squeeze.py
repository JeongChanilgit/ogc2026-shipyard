"""run_squeeze.py -- LONG-HORIZON coordinate-descent crane-repack squeeze.

Models the real eval server's 10-30 min per-instance budget. Repeatedly applies
crane_cpsat.crane_repack_bay (position[x,y,o] + timing) to tardy bays over many
rounds until the time budget is exhausted or no bay improves. Each round
re-generates candidates around the CURRENT poses, so the search walks toward
better layouts (true coordinate descent). Every accepted move passes the
OFFICIAL full-solution checker → never-worse in full objective.

Per-bay time within a round is split proportional to the bay's current z1
(squeeze the worst bays hardest).

Usage: python run_squeeze.py [prob=prob_38] [total_time_s=600] [n_xcand=5] [n_ycand=0] [n_ocand=0]
"""
import sys
import os
import json
import copy
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter          # noqa: E402
import seed as S        # noqa: E402
import crane_cpsat as C # noqa: E402


def _bz1(data, pl):
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in pl)


def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    nxc = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    nyc = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    noc = int(sys.argv[5]) if len(sys.argv) > 5 else 0

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

    print(f"=== {prob} SQUEEZE  (TL={tl:.0f}s nxc={nxc} nyc={nyc} noc={noc}) ===", flush=True)
    print(f"BEFORE obj={base['obj']} z1={base['z1']} z2={base['z2']} z3={base['z3']} "
          f"feas={base['feasible']}", flush=True)
    if not base["feasible"]:
        print("infeasible -- abort", flush=True)
        return

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
        zsum = float(sum(z for _, z in bays_t)) or 1.0
        improved = False
        for j, z1 in bays_t:
            now = time.monotonic()
            if now >= deadline - 1.0:
                break
            remain = deadline - now
            # proportional to this bay's z1 share, but never less than 20s and
            # never more than the remaining budget.
            per = max(20.0, min(remain, remain * (z1 / zsum)))
            try:
                new_pl, st, wall, info = C.crane_repack_bay(
                    data, j, cur[j], per, n_xcand=nxc, n_ycand=nyc, n_ocand=noc)
            except TypeError:
                # crane_repack_bay without n_ocand yet -> fall back to x/y only
                new_pl, st, wall, info = C.crane_repack_bay(
                    data, j, cur[j], per, n_xcand=nxc, n_ycand=nyc)
            if new_pl is None:
                print(f"  r{rnd} bay{j} z1={int(z1)} no-sol ({st})", flush=True)
                continue
            trial = dict(cur)
            trial[j] = new_pl
            ev = S.global_eval(data, trial)
            nz = _bz1(data, new_pl)
            if ev["feasible"] and ev["obj"] < cur_obj - 1e-6:
                cur = trial
                cur_obj = ev["obj"]
                improved = True
                print(f"  r{rnd} bay{j} z1={int(z1)}->{int(nz)} ACCEPT obj->{ev['obj']:.0f} "
                      f"({wall:.0f}s {st})", flush=True)
            else:
                print(f"  r{rnd} bay{j} z1={int(z1)}->{int(nz)} reject "
                      f"(feas={ev['feasible']}) ({wall:.0f}s {st})", flush=True)
        if not improved:
            print(f"round {rnd}: no improvement -- converged", flush=True)
            break

    after = S.global_eval(data, cur)
    d = after["obj"] - base["obj"]
    print(f"AFTER  obj={after['obj']} z1={after['z1']} z2={after['z2']} z3={after['z3']} "
          f"feas={after['feasible']}", flush=True)
    print(f"delta  {d:+.0f} ({d / base['obj'] * 100:+.2f}%)  rounds={rnd} "
          f"wall={time.monotonic() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
