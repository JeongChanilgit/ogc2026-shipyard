"""Prototype cycle 10: z3-AWARE minimal reassignment local search.
Start at preferred (z3=0). Repeatedly relieve the tardy bay by moving ONE block
to its cheapest-z3 alternative fitting bay, re-pack (cells), accept iff total obj
improves. Goal: reach z1≈0 at SMALL z3 (the competitor regime), not crude spill."""
import json, sys, time, math
from pathlib import Path
ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
import ogc_analysis as OA
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M
from utils import Bay

names = sys.argv[1:] or ['prob_3', 'prob_9', 'prob_11', 'prob_15', 'prob_16']
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']


def pack_members(members, bays, blocks, n, budget):
    M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
    placements = {}
    pt = M._pack_all(members, placements, bays, blocks, time.monotonic() + budget, mode='cells')
    if pt is None or len(pt) != n:
        return None
    return M._build(placements, pt, n)


for name in names:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    nb = len(bays)
    comp = COMP.get(name, {})
    fits = {b: M._fits_per_bay(b, blocks[b], bays) for b in range(n)}
    prefs = {b: blocks[b].get('bay_preferences', [0.0]*nb) for b in range(n)}
    # current bay assignment per block (start: preferred)
    assign = {}
    _, members0 = M._assign_preferred(blocks, bays)
    for j, mem in enumerate(members0):
        for b in mem:
            assign[b] = j

    def members_from(assign):
        m = [[] for _ in range(nb)]
        for b, j in assign.items():
            m[j].append(b)
        return m

    def evaluate(assign):
        sol = pack_members(members_from(assign), bays, blocks, n, 25)
        if sol is None:
            return None
        return OA.obj_tuple(prob, sol)  # feas,obj,z1,z2,z3

    cur = evaluate(assign)
    t0 = time.monotonic()
    moves = 0
    while cur is not None and cur[2] > 0 and time.monotonic() - t0 < 60 and moves < 40:
        feas, obj, z1, z2, z3 = cur
        # find tardy blocks (exit>due) per current packing
        sol = pack_members(members_from(assign), bays, blocks, n, 25)
        tardy = []
        for t, ops in sol['operations'].items():
            for op in ops:
                if op['type'] == 'EXIT':
                    b = op['block_id']
                    if int(t) > int(blocks[b]['due_date']):
                        tardy.append(b)
        # candidate moves: any block in a bay that HAS tardy blocks, to a cheaper-z1
        # alt bay, ranked by z3 cost (ascending)
        tardy_bays = set(assign[b] for b in tardy)
        cands = []
        for b in range(n):
            if assign[b] not in tardy_bays:
                continue
            cur_pref = prefs[b][assign[b]]
            for j2 in fits[b]:
                if j2 == assign[b]:
                    continue
                z3cost = cur_pref - prefs[b][j2]   # >=0 if moving to worse bay
                cands.append((z3cost, b, j2))
        cands.sort(key=lambda c: c[0])
        best_obj = obj; best_mv = None; best_eval = None
        for z3cost, b, j2 in cands[:25]:    # try the 25 cheapest-z3 moves
            old = assign[b]; assign[b] = j2
            ev = evaluate(assign)
            assign[b] = old
            if ev is not None and ev[0] and ev[1] < best_obj - 1e-6:
                best_obj = ev[1]; best_mv = (b, j2); best_eval = ev
                if ev[2] == 0:
                    break   # reached z1=0, take it
        if best_mv is None:
            break
        assign[best_mv[0]] = best_mv[1]
        cur = best_eval; moves += 1

    f = cur if cur else (False, math.inf, -1, -1, -1)
    cw = '  BEAT' if (comp.get('obj') and f[1] < comp['obj']) else ''
    print(f"{name:<9} moves={moves:>2}  final z1={f[2]:.0f} z3={f[4]:.0f} obj={f[1]:.0f}  "
          f"| comp obj={comp.get('obj',0):.0f} z3={comp.get('z3','?')}{cw}")
