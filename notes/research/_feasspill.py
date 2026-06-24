"""DECISIVE goal test (v2): FORCED targeted spill, cells-guided (fast), with periodic
box-decomp+cumulative measurement. Spill the cheapest-z3 block from the most-tardy
bay (cells z1, fast) one at a time; every MEASURE steps, full box-decomp pack to read
the TRUE (z1, z3, obj). Question: does z1 -> ~0 as z3 climbs toward the competitor's
~435? If yes at z3~hundreds -> path to set1<1M. If z1 stays high -> realize wall.
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

os.environ.setdefault('OGC_BD_CUMUL', '1')
os.environ.setdefault('OGC_BD_WORKERS', '4')
TARGET = sys.argv[1] if len(sys.argv) > 1 else 'prob_13'
CELLTL = float(os.environ.get('FS_CELLTL', '4'))     # cells budget per bay (fast guide)
FINALTL = float(os.environ.get('FS_FINALTL', '100')) # box-decomp full-pack budget
MEASURE = int(os.environ.get('FS_MEASURE', '4'))     # measure every N spills
MAXSTEPS = int(os.environ.get('FS_MAXSTEPS', '24'))
COMP = json.load(open('notes/competitor-2026-06-11.json', encoding='utf-8'))['competitor']
c12 = json.load(open('notes/research/baselines/c12.json'))

prob = json.load(open(f'instances/train/{TARGET}.json', encoding='utf-8'))
blocks = prob['blocks']; n = len(blocks); nb = len(prob['bays'])
bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
D = {b: int(blocks[b]['due_date']) for b in range(n)}
prefs = {b: blocks[b].get('bay_preferences', [0.0] * nb) for b in range(n)}
smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
fits = {b: M._fits_per_bay(b, blocks[b], bays) for b in range(n)}
cm = COMP.get(TARGET, {}).get('obj'); co = c12.get(TARGET, {}).get('obj')


def cells_z1(mem, j):
    if not mem:
        return 0.0
    r = M._pack_bay_copresent(mem, blocks, bays[j], time.monotonic() + CELLTL, cells=True)
    if r is None:
        return 1e9
    return sum(max(0, r[b][4] - D[b]) for b in mem)


def measure(members, label):
    mem_lists = [list(m) for m in members]
    M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
    r = M._pack_members(mem_lists, bays, blocks, n, prob, time.monotonic() + FINALTL, 'boxdecomp')
    if not r:
        print(f"   [{label}] final pack failed")
        return
    feas, o2, z1, z2, z3 = OA.obj_tuple(prob, r[1])
    tag = 'BEAT-COMP' if (cm and o2 < cm) else ('beat-c12' if (co and o2 < co - 1) else '')
    print(f"   [{label}] BD z1={z1:.0f} z2={z2:.0f} z3={z3:.0f} obj={o2:.0f}  comp={cm:.0f}  {tag}",
          flush=True)


_, mem0 = M._assign_preferred(blocks, bays)
members = [set(m) for m in mem0]
z3 = 0.0
print(f"[{TARGET}] comp={cm:.0f} c12={co:.0f} | CELLTL={CELLTL} FINALTL={FINALTL}")
print(f"{'step':>5}{'cellz1':>9}{'z3':>8}  moved")
M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
ctard = [cells_z1(members[j], j) for j in range(nb)]
print(f"{0:>5}{sum(ctard):>9.0f}{z3:>8.0f}  (preferred)")
measure(members, "k=0")
for step in range(1, MAXSTEPS + 1):
    if sum(ctard) <= 0:
        break
    j = max(range(nb), key=lambda k: ctard[k])
    movable = [b for b in members[j] if any(k != j for k in fits[b])]
    if not movable:
        print("  (no movable block in tardy bay)")
        break
    b = min(movable, key=lambda b: (smax[b] - max(prefs[b][k] for k in fits[b] if k != j)))
    j2 = max((k for k in fits[b] if k != j), key=lambda k: prefs[b][k])
    members[j].discard(b); members[j2].add(b)
    z3 += (smax[b] - prefs[b][j2]) - (smax[b] - prefs[b][j])
    ctard[j] = cells_z1(members[j], j)
    ctard[j2] = cells_z1(members[j2], j2)
    print(f"{step:>5}{sum(ctard):>9.0f}{z3:>8.0f}  blk{b} {j}->{j2}", flush=True)
    if step % MEASURE == 0:
        measure(members, f"k={step}")
measure(members, "final")
