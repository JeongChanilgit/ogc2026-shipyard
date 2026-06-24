"""Cycle-16 PROTOTYPE — minimal-spill reassignment guided by the ACCURATE cells
decode (not the bbox proxy that makes _solve_reassign over-spill z3 to 7659-10802).

Diagnosis (INSIGHTS cyc13-15): for prob_12/13/14/20 the dominant obj term is the
z3 OVER-spill. Energetic forced-spill LB is ≤39 z3; the competitor lives at z3
~330-460 with z1=0. Our generators (capped / bbox-proxy reassign) spill to ~9000+
because they measure congestion with LOOSE bbox/area. This prototype instead:
  start at preferred (z3≈0) → pack each bay with CELLS (accurate z1) → while tardy,
  spill the cheapest-z3 block that most reduces TRUE obj (cells-verified) → repeat →
  final-pack the low-z3 assignment with box-decomp (best z1 realizer).
Goal: land near the competitor regime (z1≈0 at z3 a few hundred) ⇒ WIN.

Test:  conda run -n ogc2025 python notes/research/_minspill.py prob_13 prob_14 prob_20
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'src'))
import ogc_analysis as OA                               # noqa: E402
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M                                 # noqa: E402
from utils import Bay                                   # noqa: E402

os.environ['OGC_CPSAT'] = '1'
TARGETS = sys.argv[1:] or ['prob_13', 'prob_14', 'prob_20']
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
c12 = json.load(open('notes/research/baselines/c12.json'))
TL = float(os.environ.get('MS_TL', '40'))            # per-instance search budget
CAND = int(os.environ.get('MS_CAND', '6'))           # cells-verified candidates/step
GUIDE = os.environ.get('MS_GUIDE', 'cells')          # guidance packer
FINAL = os.environ.get('MS_FINAL', 'boxdecomp')      # final packer


def packbay_z1(mem, blocks, bay, dl, mode):
    """Pack one bay, return (layout, tardiness) using `mode` geometry."""
    if not mem:
        return {}, 0.0
    if mode == 'boxdecomp':
        r = M._pack_bay_boxdecomp(mem, blocks, bay, dl, max(0.0, dl - time.monotonic()))
    else:
        r = M._pack_bay_copresent(mem, blocks, bay, dl, cells=(mode != 'bbox'))
    if r is None:
        return None, float('inf')
    D = {b: int(blocks[b]['due_date']) for b in mem}
    t = sum(max(0, r[b][4] - D[b]) for b in mem)
    return r, t


def run(name):
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    nb = len(bays)
    w1 = prob.get('weights', {}).get('w1', 1.0)
    w3 = prob.get('weights', {}).get('w3', 1.0)
    M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
    fits = {b: M._fits_per_bay(b, blocks[b], bays) for b in range(n)}
    prefs = {b: blocks[b].get('bay_preferences', [0.0] * nb) for b in range(n)}
    smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
    _, mem0 = M._assign_preferred(blocks, bays)
    members = [set(m) for m in mem0]
    assign = {b: j for j in range(nb) for b in members[j]}
    t0 = time.monotonic()
    dl = t0 + TL
    pcache = {}

    def pb(j, mem):
        key = (j, frozenset(mem))
        if key not in pcache:
            pcache[key] = packbay_z1(mem, blocks, bays[j], min(dl, time.monotonic() + 6), GUIDE)
        return pcache[key]

    tard = [pb(j, members[j])[1] for j in range(nb)]
    z3 = sum(smax[b] - prefs[b][assign[b]] for b in range(n))
    steps = 0
    while sum(tard) > 0 and time.monotonic() < dl:
        tardy = [j for j in range(nb) if tard[j] > 0]
        # candidate spill moves ranked by z3 cost ascending (cheapest spill first)
        cands = []
        for j in tardy:
            for b in members[j]:
                for j2 in fits[b]:
                    if j2 != j:
                        cands.append((smax[b] - prefs[b][j2] - (smax[b] - prefs[b][j]),
                                      b, j, j2))
        cands.sort(key=lambda c: c[0])
        best_mv = None; best_dobj = -1e-9
        for (dz3, b, j, j2) in cands[:CAND]:
            if time.monotonic() >= dl:
                break
            ts = pb(j, members[j] - {b})[1]
            td = pb(j2, members[j2] | {b})[1]
            if ts == float('inf') or td == float('inf'):
                continue
            dz1 = (ts + td) - (tard[j] + tard[j2])
            dobj = w1 * dz1 + w3 * dz3
            if dobj < best_dobj:
                best_dobj = dobj; best_mv = (b, j, j2, ts, td, dz3)
        if best_mv is None:
            break
        b, j, j2, ts, td, dz3 = best_mv
        members[j].discard(b); members[j2].add(b); assign[b] = j2
        tard[j] = ts; tard[j2] = td; z3 += dz3; steps += 1

    # final pack with the strong realizer (box-decomp+cumulative; long budget)
    mem_lists = [list(m) for m in members]
    ftl = float(os.environ.get('MS_FINALTL', '120'))
    r = M._pack_members(mem_lists, bays, blocks, n, prob, time.monotonic() + ftl, FINAL)
    if r is None:
        r = M._pack_members(mem_lists, bays, blocks, n, prob, time.monotonic() + 20, 'cells')
    obj, sol = r
    feas, o2, fz1, fz2, fz3 = OA.obj_tuple(prob, sol)
    co = c12.get(name, {}).get('obj'); cm = COMP.get(name, {}).get('obj')
    tag = 'BEAT-COMP' if (cm and o2 < cm) else ('beat-c12' if (co and o2 < co - 1) else '')
    print(f"{name:<9} steps={steps:>3} z1={fz1:>5.0f} z3={fz3:>6.0f} obj={o2:>12.0f} "
          f"c12={(co or 0):>12.0f} comp={(cm or 0):>10.0f} {tag}")
    return o2


if __name__ == '__main__':
    print(f"[minspill] GUIDE={GUIDE} FINAL={FINAL} TL={TL} CAND={CAND}")
    print(f"{'inst':<9}{'':>10}{'':>9}{'':>9}{'obj':>12}{'c12':>14}{'comp':>13}")
    tot = 0.0
    for nm in TARGETS:
        tot += run(nm)
    print(f"TOTAL={tot:.0f}")
