"""WHY-analysis (INSIGHTS backlog #1) — cheap, no decode.

For the 5 hard set1 instances, decide the LEVER: is a z1=0 + near-preferred
(low-z3) assignment even area-time FEASIBLE under the PREFERRED map?

Method: energetic reasoning (sound cumulative LB). Treat each bay as a 1-D
cumulative resource of capacity C = W*H over time. Each block must run for p in
[release, due] for zero tardiness (exit<=due), consuming footprint-area * p of
area-time (footprint = union of all layers = the crane-binding base, min over
orientations -> a LOWER bound on consumed area => a SOUND infeasibility cert).
For every interval [t1,t2] (breakpoints = releases x dues) the mandatory work
  W(b)=max(0,min(t2-t1, p_b, r_b+p_b-t1, t2-(d_b-p_b)))
Sum a_b*W(b) > C*(t2-t1)  =>  z1=0-at-preferred is PROVABLY infeasible on that
bay over [t1,t2]  =>  spill is MANDATORY (lever = assignment search).
If no bay overloads -> area says z1=0-at-preferred is feasible -> our PACKING is
the weak link and our current z3 spill is gratuitous.

Also: greedy min-z3 removal (ignoring destination capacity = a LOWER bound on
forced z3) to make each bay area-feasible, vs competitor z3 and our c12 z3.
"""
import json
import sys
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'src'))
from utils import Bay, Block, _poly_from_verts          # noqa: E402
import myalgorithm as M                                 # noqa: E402

TARGETS = sys.argv[1:] or ['prob_11', 'prob_12', 'prob_13', 'prob_14', 'prob_20']
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
ALL = {r['inst']: r for r in json.load(open('notes/research/_alldata.json'))['rows']}


def footprint_area(b, bd):
    """Min over orientations of union-of-layers footprint area (true polygon)."""
    from shapely.ops import unary_union
    best = None
    for oi in range(len(bd.get('shape', []) or [])):
        layers = Block(b, bd, 0, 0, oi).layers_at_pos()
        polys = [p for p in (_poly_from_verts(l) for l in layers) if p is not None]
        if not polys:
            continue
        a = unary_union(polys).area
        best = a if best is None else min(best, a)
    return best or 1.0


def energetic(members, blocks, area, C):
    """Return (worst_ratio, overloaded_intervals[(t1,t2,excess_areatime)])."""
    if not members:
        return 0.0, []
    R = {b: int(blocks[b]['release_time']) for b in members}
    P = {b: int(blocks[b]['processing_time']) for b in members}
    D = {b: int(blocks[b]['due_date']) for b in members}
    t1s = sorted({R[b] for b in members})
    t2s = sorted({D[b] for b in members})
    worst = 0.0
    over = []
    for t1 in t1s:
        for t2 in t2s:
            if t2 <= t1:
                continue
            req = 0.0
            for b in members:
                w = min(t2 - t1, P[b], R[b] + P[b] - t1, t2 - (D[b] - P[b]))
                if w > 0:
                    req += area[b] * w
            avail = C * (t2 - t1)
            if req > avail + 1e-6:
                over.append((t1, t2, req - avail))
                worst = max(worst, req / avail)
    return worst, over


def forced_z3(members0, blocks, area, C, prefs, smax, fits):
    """Greedy cheapest-z3 removal (dest capacity IGNORED = LB on forced z3) until
    the bay is area-feasible. Returns (total_z3, n_removed)."""
    members = list(members0)
    total = 0.0
    nrm = 0
    for _ in range(len(members0) + 2):
        worst, over = energetic(members, blocks, area, C)
        if not over:
            break
        t1, t2, _exc = max(over, key=lambda o: o[2])
        best_b, best_cost = None, None
        for b in members:
            R = int(blocks[b]['release_time'])
            P = int(blocks[b]['processing_time'])
            D = int(blocks[b]['due_date'])
            w = min(t2 - t1, P, R + P - t1, t2 - (D - P))
            if w <= 0:
                continue
            alts = [k for k in fits.get(b, {}) if k not in cur_bay_of[b]]
            if not alts:
                continue
            mv = min(smax[b] - prefs[b][k] for k in alts)   # >=0, z3 paid to move
            ratio = mv / (area[b] * w + 1e-9)               # z3 per unit relief
            if best_cost is None or ratio < best_cost:
                best_cost, best_b = ratio, b
                best_mv = mv
        if best_b is None:
            break       # cannot relieve (no alt bays) -> structurally stuck
        members.remove(best_b)
        total += best_mv
        nrm += 1
    return total, nrm


print(f"{'inst':<9}{'bay':>4}{'nblk':>6}{'C=WH':>10}{'feas?':>7}{'worstRatio':>12}"
      f"{'#over_iv':>10}")
print('-' * 60)
for name in TARGETS:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']
    n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    M._FP_CACHE.clear()
    M._LAYER_CACHE.clear()
    area = {b: footprint_area(b, blocks[b]) for b in range(n)}
    placements, members = M._assign_preferred(blocks, bays)
    fits = {b: M._fits_per_bay(b, blocks[b], bays) for b in range(n)}
    prefs = {b: blocks[b].get('bay_preferences', [0.0] * len(bays)) for b in range(n)}
    smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
    cur_bay_of = {b: {placements[b][0]} for b in range(n)}
    globals()['cur_bay_of'] = cur_bay_of

    # confirm preferred z3 ~ 0
    pref_z3 = sum(smax[b] - prefs[b][placements[b][0]] for b in range(n))
    any_over = False
    tot_forced = 0.0
    for j in range(len(bays)):
        C = max(1.0, bays[j].width * bays[j].height)
        worst, over = energetic(members[j], blocks, area, C)
        feas = 'YES' if not over else 'NO'
        if over:
            any_over = True
        print(f"{name:<9}{j:>4}{len(members[j]):>6}{C:>10.0f}{feas:>7}"
              f"{worst:>12.2f}{len(over):>10}")
        if over:
            fz, nrm = forced_z3(members[j], blocks, area, C, prefs, smax, fits)
            tot_forced += fz
            print(f"           -> forced spill LB to relieve bay {j}: "
                  f"z3>={fz:.0f} (removed {nrm} blks)")
    row = ALL.get(name, {})
    cz3 = COMP.get(name, {}).get('z3')
    print(f"  [{name}] pref_z3={pref_z3:.0f}  z1=0-at-preferred area-feasible="
          f"{'NO (spill mandatory)' if any_over else 'YES (packing is the lever)'}"
          f"  forced_z3_LB={tot_forced:.0f}  comp_z3={cz3}  our_c12_z3={row.get('z3')}")
    print()
