"""H7 verification (no external deps, no legacy modification): does block ORDER
materially change a congested bay's tardiness under the legacy fastfloor decoder?
If random orders beat the F0-F3 catalog, more order-search (GRASP/beam) is a cheap
density win. Also probes whether the BL decoder leaves tardiness on the table.

Test on prob_20's preferred magnet bay (the over-subscribed one, biggest z3 loss).
"""
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT / 'src'))                 # fastfloor, utils
sys.path.insert(0, str(ROOT / 'notes' / 'research'))  # freshstart (_assign_preferred)
import fastfloor as FF                                # noqa: E402
import freshstart as FS                               # noqa: E402
from utils import Bay                                 # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else 'prob_20'
prob = json.load(open(f'instances/train/{name}.json', encoding='utf-8'))
blocks = prob['blocks']
bays = [Bay.from_dict(d, i) for i, d in enumerate(prob['bays'])]
_, members = FS._assign_preferred(blocks, bays)
# most-loaded (most blocks) bay = the congested magnet bay
j = max(range(len(bays)), key=lambda k: len(members[k]))
ids = list(members[j])
print(f"[{name}] congested bay {j}: {len(ids)} blocks (preferred assignment)")


def tard_of(order):
    asgn, ft = FF._fixed_time_decode(bays[j], j, order, blocks,
                                     time.monotonic() + 8.0, order)
    return ft['ft_tard'] if asgn is not None else float('inf')


# F0-F3 catalog orders
cat = {}
for ok in ('F0', 'F1', 'F2', 'F3'):
    order = FF._ft_order(ids, blocks, ok)
    cat[ok] = tard_of(order)
print("catalog:", {k: round(v) for k, v in cat.items()})
best_cat = min(cat.values())

# random orders
rng = random.Random(1)
rand_t = []
t0 = time.monotonic()
for r in range(40):
    if time.monotonic() - t0 > 90:
        break
    order = ids[:]
    rng.shuffle(order)
    rand_t.append(tard_of(order))
rand_t.sort()
print(f"random({len(rand_t)}): min={rand_t[0]:.0f} med={rand_t[len(rand_t)//2]:.0f} "
      f"max={rand_t[-1]:.0f}")
beat = sum(1 for v in rand_t if v < best_cat - 1e-9)
print(f"best catalog={best_cat:.0f}  best random={rand_t[0]:.0f}  "
      f"random orders beating catalog: {beat}/{len(rand_t)}")
print(">>> ORDER MATTERS" if rand_t[0] < best_cat - 1e-9 else ">>> catalog already best")
