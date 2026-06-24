"""run_lns.py -- LARGE NEIGHBORHOOD SEARCH crane-repack over a submission solution.

Monolithic crane_cpsat on a big bay (100+ blocks) only ever reaches FEASIBLE in
its time budget -- the subproblem is too large to prove OPTIMAL.  LNS fixes this:
each round it FREEZES most of a bay and optimises a small FREE subset (<= max_free
blocks) to OPTIMAL, then GATES the move on the OFFICIAL full-solution objective
(never-worse).  Free subsets are drawn from TIME-OVERLAP COMPONENTS -- maximal
groups of blocks whose [entry, exit) intervals transitively overlap.  These are
exactly the crane-serialization units (only co-present blocks contend for the
crane / floor space), so optimising one component at a time is the right
neighbourhood: frozen blocks outside the component never co-exist with the free
ones at the boundary anyway, so freezing them costs nothing structurally.

Usage:
    python run_lns.py [prob=prob_38] [total_time_s=600] [max_free=35]
                      [per_window_s=30] [n_xcand=5]
"""
import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter          # noqa: E402
import seed as S        # noqa: E402
import crane_cpsat as C # noqa: E402


def _bz1(data, pl):
    """Single-bay z1 (tardiness) of a placed list."""
    return sum(max(0, p["exit"] - data["blocks"][p["id"]]["due_date"]) for p in pl)


def _lateness(data, p):
    """exit - due (can be negative); used to prioritise tardy blocks."""
    return p["exit"] - data["blocks"][p["id"]]["due_date"]


# ---------------------------------------------------------------------------
def _time_overlap_components(placed):
    """Connected components over the "[entry, exit) intervals overlap" relation.

    Two blocks are linked if their half-open lifetime intervals overlap:
        a.entry < b.exit  AND  b.entry < a.exit
    Transitive closure (union-find) yields co-presence CLUSTERS -- the crane /
    floor contention units.  Returns a list of sets of block ids.
    """
    items = [(p["id"], int(p["entry"]), int(p["exit"])) for p in placed]
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    # sweep-line by entry: only blocks still "open" can overlap the next one.
    order = sorted(range(n), key=lambda k: items[k][1])
    active = []   # indices of intervals whose exit > current entry
    for k in order:
        bid, en, ex = items[k]
        # drop intervals that have already exited (exit <= this entry => no overlap)
        active = [a for a in active if items[a][2] > en]
        for a in active:
            # items[a] entered earlier (or equal); they overlap iff a.exit > en
            # AND k.exit > a.entry.  a.exit > en is guaranteed by the filter; the
            # half-open relation a.entry < k.exit holds since a.entry <= en < ex.
            union(a, k)
        active.append(k)

    groups: dict = {}
    for k in range(n):
        groups.setdefault(find(k), set()).add(items[k][0])
    return list(groups.values())


# ---------------------------------------------------------------------------
def _chunks_for_component(data, placed, comp_ids, max_free):
    """Split a component's ids into chunks of <= max_free, tardy-first.

    Sort the component's blocks by current lateness (exit-due) descending so the
    most-tardy blocks land together in the first chunk(s); take consecutive
    windows of max_free.  A single chunk if the component already fits.
    """
    if len(comp_ids) <= max_free:
        return [set(comp_ids)]
    by_id = {p["id"]: p for p in placed}
    ordered = sorted(comp_ids, key=lambda b: -_lateness(data, by_id[b]))
    return [set(ordered[i:i + max_free]) for i in range(0, len(ordered), max_free)]


# ---------------------------------------------------------------------------
def main():
    prob = sys.argv[1] if len(sys.argv) > 1 else "prob_38"
    total_time_s = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    max_free = int(sys.argv[3]) if len(sys.argv) > 3 else 35
    per_window_s = float(sys.argv[4]) if len(sys.argv) > 4 else 30.0
    nxc = int(sys.argv[5]) if len(sys.argv) > 5 else 5

    data = json.load(open(os.path.join("..", "instances", "train", prob + ".json"),
                          encoding="utf-8"))
    real = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f"real_{prob}.json")
    if not os.path.isfile(real):
        print(f"missing {real}", flush=True)
        return
    sol = json.load(open(real, encoding="utf-8"))
    cur = adapter.deserialize(data, sol)
    base = S.global_eval(data, cur)
    cur_obj = base["obj"]

    print(f"=== {prob} LNS  (TL={total_time_s:.0f}s max_free={max_free} "
          f"per_window={per_window_s:.0f}s nxc={nxc}) ===", flush=True)
    print(f"BEFORE obj={base['obj']} z1={base['z1']} z2={base['z2']} "
          f"z3={base['z3']} feas={base['feasible']}", flush=True)
    if not base["feasible"]:
        print("infeasible -- abort", flush=True)
        return

    start = time.monotonic()
    deadline = start + total_time_s
    rnd = 0
    n_opt = n_feas = n_other = 0
    while time.monotonic() < deadline - 1.0:
        rnd += 1
        # tardy bays, worst z1 first
        bays_t = [(j, _bz1(data, pl)) for j, pl in cur.items()]
        bays_t = [(j, z) for j, z in bays_t if z > 0]
        bays_t.sort(key=lambda x: -x[1])
        if not bays_t:
            print(f"round {rnd}: no tardy bay -- done", flush=True)
            break

        improved = False
        for j, bay_z1 in bays_t:
            if time.monotonic() >= deadline - 1.0:
                break
            placed = cur[j]
            by_id = {p["id"]: p for p in placed}
            # time-overlap components, keep only those containing a tardy block
            comps = _time_overlap_components(placed)
            tardy_ids = {p["id"] for p in placed if _lateness(data, p) > 0}
            comps = [c for c in comps if c & tardy_ids]
            # bigger / more-tardy components first
            comps.sort(key=lambda c: -sum(max(0, _lateness(data, by_id[b]))
                                          for b in c))
            for comp in comps:
                if time.monotonic() >= deadline - 1.0:
                    break
                for chunk in _chunks_for_component(data, placed, comp, max_free):
                    if time.monotonic() >= deadline - 1.0:
                        break
                    # only worth solving if the chunk holds >=1 tardy block
                    if not (chunk & tardy_ids):
                        continue
                    z1_before = sum(max(0, _lateness(data, by_id[b]))
                                    for b in chunk)
                    remain = deadline - time.monotonic()
                    per = min(per_window_s, max(5.0, remain))
                    t_call = time.monotonic()
                    try:
                        new_pl, st, wall, info = C.crane_repack_bay(
                            data, j, placed, per, n_xcand=nxc,
                            free_ids=chunk)
                    except Exception as ex:
                        print(f"  r{rnd} bay{j} chunk(free={len(chunk)}) "
                              f"EXC {type(ex).__name__}: {ex}", flush=True)
                        continue
                    call_wall = time.monotonic() - t_call
                    if st == "OPTIMAL":
                        n_opt += 1
                    elif st == "FEASIBLE":
                        n_feas += 1
                    else:
                        n_other += 1
                    if new_pl is None:
                        print(f"  r{rnd} bay{j} free={len(chunk)} z1b={int(z1_before)} "
                              f"no-sol ({st}) {call_wall:.0f}s", flush=True)
                        continue
                    z1_after = sum(
                        max(0, p["exit"] - data["blocks"][p["id"]]["due_date"])
                        for p in new_pl if p["id"] in chunk)
                    trial = {**cur, j: new_pl}
                    ev = S.global_eval(data, trial)
                    accept = ev["feasible"] and ev["obj"] < cur_obj - 1e-6
                    if accept:
                        cur = trial
                        cur_obj = ev["obj"]
                        placed = cur[j]
                        by_id = {p["id"]: p for p in placed}
                        improved = True
                    print(f"  r{rnd} bay{j} free={len(chunk)} "
                          f"z1{int(z1_before)}->{int(z1_after)} obj->{ev['obj']:.0f} "
                          f"{'ACCEPT' if accept else 'reject'} "
                          f"(feas={ev['feasible']}) {st} {call_wall:.0f}s", flush=True)
        if not improved:
            print(f"round {rnd}: no improvement -- converged", flush=True)
            break

    after = S.global_eval(data, cur)
    d = after["obj"] - base["obj"]
    print(f"AFTER  obj={after['obj']} z1={after['z1']} z2={after['z2']} "
          f"z3={after['z3']} feas={after['feasible']}", flush=True)
    print(f"delta  {d:+.0f} ({d / base['obj'] * 100:+.2f}%)  rounds={rnd} "
          f"wall={time.monotonic() - start:.0f}s  "
          f"chunks: OPTIMAL={n_opt} FEASIBLE={n_feas} other={n_other}", flush=True)


if __name__ == "__main__":
    main()
