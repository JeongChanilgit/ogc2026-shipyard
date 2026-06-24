"""THE <1M lever: targeted-spill (low-z3 assignment) + OLD realizer (fastfloor
_fixed_time_decode FLOOR + _cpsat_bay_timing_verified ORACLE). The old solver's own
ban-race over-spills (prob_13 z1=0 only at z3=805); the competitor realizes z1=0 at
z3=435. Does a CONSERVATIVE targeted-spill + the old oracle realize z1=0 at z3 BELOW
the competitor? If yes on the big-z3 losses -> set1 < 1M.

Per spill step: decode every bay with the floor (best of F0-F3), assemble results,
run the timing oracle, report (z3, floor_z1, oracle_obj) via check_feasibility.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'src'))                 # utils, fastfloor, myalgorithm(OLD)
sys.path.insert(0, str(ROOT / 'notes' / 'research'))  # freshstart
import fastfloor as FF                                # noqa: E402
import myalgorithm as M                               # noqa: E402  (OLD solver: oracle)
import baseline_greedy as BG                          # noqa: E402  (_build_operations)
import freshstart as FS                               # noqa: E402
from utils import Bay, check_feasibility              # noqa: E402

COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
name = sys.argv[1] if len(sys.argv) > 1 else 'prob_13'
EVERY = 2
prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
blocks = prob['blocks']; n = len(blocks); nb = len(prob['bays'])
bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
prefs = {b: blocks[b].get('bay_preferences', [0.0] * nb) for b in range(n)}
smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
fits = {b: FS._fits_per_bay(b, blocks[b], bays) for b in range(n)}
cm = COMP.get(name, {})
w = prob.get('weights', {})


def build_ops(results):
    flat = [dict(a) for by in results.values() for a in by.values()]
    return {"operations": BG._build_operations(flat)}


def decode_all(members, dl):
    results = {}
    for j in range(nb):
        if not members[j]:
            results[j] = {}
            continue
        best = None; bt = 1e18
        for ok in ('F0', 'F1', 'F2', 'F3'):
            try:
                asgn, ft = FF._fixed_time_decode(bays[j], j, list(members[j]),
                                                 blocks, dl, ok)
            except Exception:
                asgn = None
            if asgn is not None and ft['ft_tard'] < bt:
                bt = ft['ft_tard']; best = asgn
        if best is None:
            return None
        results[j] = best
    return results


def evaluate(members):
    results = decode_all(members, time.monotonic() + 8)
    if results is None:
        return None
    floor_sol = build_ops(results)
    fchk = check_feasibility(prob, floor_sol)
    floor_z1 = fchk.get('obj1', 1e9) if fchk.get('feasible') else 1e9
    best_chk = fchk
    try:
        cand = M._cpsat_bay_timing_verified(prob, bays, results,
                                            deadline=time.monotonic() + 18)
        if cand is not None:
            cchk = check_feasibility(prob, cand)
            if cchk.get('feasible') and (not best_chk.get('feasible')
                                         or cchk['objective'] < best_chk['objective']):
                best_chk = cchk
    except Exception as e:
        print(f"   oracle err: {type(e).__name__}: {e}")
    return floor_z1, best_chk, results


_, m0 = FS._assign_preferred(blocks, bays)
members = [set(m) for m in m0]
z3 = 0.0
tabu = []
print(f"[{name}] comp obj={cm.get('obj')} z1={cm.get('z1')} z3={cm.get('z3')}  "
      f"w1={w.get('w1')} w3={w.get('w3')}")
print(f"{'step':>4}{'z3':>7}{'floorZ1':>9}{'oracZ1':>8}{'oracZ3':>8}{'obj':>12}  res")
best_obj = 1e18
for step in range(0, 30):
    ev = evaluate(members)
    if ev is None:
        print(f"{step:>4}  decode failed"); break
    fz1, chk, results = ev
    o = chk.get('objective')
    if o is None:
        print(f"{step:>4}{z3:>7.0f}  INFEASIBLE (stage={chk.get('stage')})")
    else:
        best_obj = min(best_obj, o)
        tag = 'BEAT-COMP' if (cm.get('obj') and o < cm['obj']) else ''
        print(f"{step:>4}{z3:>7.0f}{fz1:>9.0f}{chk['obj1']:>8.0f}{chk['obj3']:>8.0f}"
              f"{o:>12.0f}  {tag}", flush=True)
    # spill cheapest-z3 from the most floor-tardy bay (reuse decoded results)
    btard = {j: sum(max(0, a['exit_time'] - blocks[b]['due_date'])
                    for b, a in results[j].items()) for j in range(nb)}
    if sum(btard.values()) <= 0:
        print("  >>> floor z1=0 reached"); break
    j = max(range(nb), key=lambda k: btard[k])
    movable = ([b for b in members[j] if b not in tabu and any(k != j for k in fits[b])]
               or [b for b in members[j] if any(k != j for k in fits[b])])
    if not movable:
        print("  stuck"); break
    b = min(movable, key=lambda b: smax[b] - max(prefs[b][k] for k in fits[b] if k != j))
    j2 = max((k for k in fits[b] if k != j), key=lambda k: prefs[b][k])
    members[j].discard(b); members[j2].add(b)
    z3 += (smax[b] - prefs[b][j2]) - (smax[b] - prefs[b][j])
    tabu.append(b)
    if len(tabu) > nb * 3:
        tabu = tabu[nb:]
print(f"BEST obj={best_obj:.0f}  (comp {cm.get('obj')})")
