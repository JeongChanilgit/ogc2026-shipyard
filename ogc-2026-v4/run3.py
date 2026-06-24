"""run3.py -- crane-aware repack as POST-PROCESS on a REAL solver's solution.

Loads real_<prob>.json (produced by the submission pipeline via _gen_real.py),
reconstructs per-bay placed via adapter.deserialize, then applies
crane_cpsat.crane_repack_bay to every tardy bay under the OFFICIAL
full-solution never-worse gate (seed.global_eval).

Usage: python run3.py [prob=prob_29] [total_time_s=60] [n_xcand=5]
"""
import sys
import os
import json
import copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter          # noqa: E402
import seed as S        # noqa: E402
import crane_cpsat as C # noqa: E402


def _bay_z1(data, placed):
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in placed)


def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_29"
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    nxc = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    data = json.load(open(os.path.join("..", "instances", "train", prob + ".json"),
                          encoding="utf-8"))
    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"real_{prob}.json")
    if not os.path.isfile(real):
        print(f"missing {real} -- run _gen_real.py {prob} first", flush=True)
        return
    sol = json.load(open(real, encoding="utf-8"))
    bays_placed = adapter.deserialize(data, sol)
    base = S.global_eval(data, bays_placed)

    print(f"=== {prob}  POST-PROCESS on REAL submission sol (TL={tl}s, nxc={nxc}) ===",
          flush=True)
    print(f"BEFORE obj={base['obj']} z1={base['z1']} z2={base['z2']} z3={base['z3']} "
          f"feas={base['feasible']}", flush=True)
    if not base["feasible"]:
        print("real sol reconstructs INFEASIBLE via adapter -- abort", flush=True)
        return

    cur = copy.deepcopy(bays_placed)
    cur_obj = base["obj"]
    bays_t = [(j, _bay_z1(data, pl)) for j, pl in cur.items()]
    bays_t = [(j, z) for j, z in bays_t if z > 0]
    bays_t.sort(key=lambda x: -x[1])
    print(f"tardy bays: {[(j, int(z)) for j, z in bays_t]}", flush=True)
    if not bays_t:
        print("no tardy bay -- nothing to do", flush=True)
        return

    per = max(8.0, tl / len(bays_t))
    for j, z1 in bays_t:
        try:
            new_pl, status, wall, info = C.crane_repack_bay(data, j, cur[j], per, n_xcand=nxc)
        except Exception as e:
            print(f"  bay{j} z1={int(z1)} CRASH {type(e).__name__}: {e}", flush=True)
            continue
        if new_pl is None:
            print(f"  bay{j} z1={int(z1)} no-solution ({status})", flush=True)
            continue
        trial = dict(cur)
        trial[j] = new_pl
        ev = S.global_eval(data, trial)
        nz = _bay_z1(data, new_pl)
        if ev["feasible"] and ev["obj"] < cur_obj - 1e-6:
            cur = trial
            cur_obj = ev["obj"]
            print(f"  bay{j} z1={int(z1)}->{int(nz)} ACCEPT  obj->{ev['obj']:.0f} "
                  f"({wall:.1f}s {status})", flush=True)
        else:
            print(f"  bay{j} z1={int(z1)}->{int(nz)} reject  "
                  f"(feas={ev['feasible']} obj={ev['obj']}) ({wall:.1f}s {status})", flush=True)

    after = S.global_eval(data, cur)
    d = after["obj"] - base["obj"]
    print(f"AFTER  obj={after['obj']} z1={after['z1']} z2={after['z2']} z3={after['z3']} "
          f"feas={after['feasible']}", flush=True)
    print(f"delta  {d:+.0f} ({d/base['obj']*100:+.2f}%)", flush=True)


if __name__ == "__main__":
    main()
