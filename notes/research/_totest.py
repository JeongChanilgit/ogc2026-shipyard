"""Test the OLD solver's KEY technique grafted into the fresh-start: a per-bay
CP-SAT TIMING ORACLE on a FIXED greedy layout. Positions frozen ⇒ crane/footprint
conflicts become time-independent ⇒ the problem collapses to a 1-D disjunctive
single-machine tardiness problem CP-SAT solves to optimum. Conflict = world-cell
sets intersect (can't be co-present); such pairs must be time-disjoint.

Does my greedy cells layout + timing oracle reach z1=0 on prob_20/12/14 (where
box-decomp floors z1 at 100-190)? If yes, the technique is recovered cleanly.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M                                 # noqa: E402  (fresh-start)
from utils import Bay                                   # noqa: E402
from ortools.sat.python import cp_model                 # noqa: E402

TARGETS = sys.argv[1:] or ['prob_20', 'prob_12', 'prob_14', 'prob_13']
WORKERS = int(os.environ.get('TO_WORKERS', '4'))
BAYTL = float(os.environ.get('TO_BAYTL', '20'))


def timing_oracle(members, blocks, bay, layout, deadline):
    """Re-time entries on FIXED positions to minimise bay tardiness. layout:
    {b:(x,y,oi,entry,exit)}. Returns re-timed layout (or original if no gain)."""
    P = {b: int(blocks[b]['processing_time']) for b in members}
    R = {b: int(blocks[b]['release_time']) for b in members}
    D = {b: int(blocks[b]['due_date']) for b in members}
    wc = {}
    for b in members:
        x, y, oi = layout[b][0], layout[b][1], layout[b][2]
        cells, _cb = M._footprint_cells(b, blocks[b], oi)
        wc[b] = frozenset((cx + x, cy + y) for (cx, cy) in cells)
    mem = list(members)
    conflicts = []
    for i in range(len(mem)):
        a = mem[i]
        for k in range(i + 1, len(mem)):
            c = mem[k]
            if not wc[a].isdisjoint(wc[c]):          # share a cell ⇒ can't co-present
                conflicts.append((a, c))
    H = max(layout[b][4] for b in members) + max(P.values())
    mdl = cp_model.CpModel()
    ev = {}; tard = []
    for b in members:
        ev[b] = mdl.NewIntVar(R[b], int(H), "")
        td = mdl.NewIntVar(0, int(H) + P[b], "")
        mdl.Add(td >= ev[b] + P[b] - D[b])
        tard.append(td)
        mdl.AddHint(ev[b], int(layout[b][3]))
    for (a, c) in conflicts:
        ba = mdl.NewBoolVar(""); ab = mdl.NewBoolVar("")
        mdl.Add(ev[a] + P[a] <= ev[c]).OnlyEnforceIf(ba)
        mdl.Add(ev[c] + P[c] <= ev[a]).OnlyEnforceIf(ab)
        mdl.AddBoolOr([ba, ab])
    mdl.Minimize(sum(tard))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = max(0.5, deadline - time.monotonic())
    s.parameters.num_search_workers = WORKERS
    s.parameters.random_seed = 1
    st = s.Solve(mdl)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return layout, len(conflicts)
    out = {}
    for b in members:
        e = int(s.Value(ev[b]))
        x, y, oi = layout[b][0], layout[b][1], layout[b][2]
        out[b] = (x, y, oi, e, e + P[b])
    return out, len(conflicts)


def z1_of(layout, blocks, members):
    D = {b: int(blocks[b]['due_date']) for b in members}
    return sum(max(0, layout[b][4] - D[b]) for b in members)


print(f"{'inst':<9}{'bay':>4}{'nblk':>6}{'conf':>7}{'greedy_z1':>11}{'oracle_z1':>11}{'wall':>7}")
print('-' * 60)
for name in TARGETS:
    prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
    blocks = prob['blocks']
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
    M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
    _, members = M._assign_preferred(blocks, bays)
    tot_g = tot_o = 0
    for j in range(len(bays)):
        mem = members[j]
        if not mem:
            continue
        lay = M._pack_bay_copresent(mem, blocks, bays[j], time.monotonic() + 8, cells=True)
        if lay is None:
            print(f"{name:<9}{j:>4}  greedy failed")
            continue
        gz1 = z1_of(lay, blocks, mem)
        t0 = time.monotonic()
        nl, nconf = timing_oracle(mem, blocks, bays[j], lay, time.monotonic() + BAYTL)
        dt = time.monotonic() - t0
        oz1 = z1_of(nl, blocks, mem)
        tot_g += gz1; tot_o += oz1
        print(f"{name:<9}{j:>4}{len(mem):>6}{nconf:>7}{gz1:>11.0f}{oz1:>11.0f}{dt:>7.1f}", flush=True)
    print(f"  [{name}] TOTAL greedy_z1={tot_g:.0f}  oracle_z1={tot_o:.0f}")
    print()
