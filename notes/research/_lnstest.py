"""Direct per-bay LNS instrumentation on one instance: budget, iters, z1 before/after."""
import json
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'src'))
import myalgorithm as M                                 # noqa: E402
from utils import Bay                                   # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else 'prob_11'
budget = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
blocks = prob['blocks']
bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
M._FP_CACHE.clear(); M._LAYER_CACHE.clear()
_, members = M._assign_preferred(blocks, bays)
D = {b: int(blocks[b]['due_date']) for b in range(len(blocks))}


def z1_of_layout(layout):
    return sum(max(0, layout[b][4] - D[b]) for b in layout)


tot_l0 = tot_lns = 0
for j in range(len(bays)):
    mem = members[j]
    if not mem:
        continue
    L0 = M._pack_bay_copresent(mem, blocks, bays[j], time.monotonic() + 5, cells=True)
    z0 = z1_of_layout(L0) if L0 else -1
    t0 = time.monotonic()
    res = M._pack_bay_lns(mem, blocks, bays[j], t0 + budget)
    dt = time.monotonic() - t0
    z1 = z1_of_layout(res) if res else -1
    tot_l0 += z0; tot_lns += z1
    print(f"bay {j}: nblk={len(mem):>3}  L0_z1={z0:>5}  LNS_z1={z1:>5}  wall={dt:>6.1f}s")
print(f"TOTAL  L0_z1={tot_l0}  LNS_z1={tot_lns}")
