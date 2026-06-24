"""Probe: WHY do congested preferred bays produce tardiness?

For the z3-optimal (uncapped) assignment, per bay decode tardy under fixed-time
(entry=R).  For each such bay ask two diagnostic questions:

  (1) AREA: peak simultaneous footprint demand / bay area, over the [R,R+P]
      windows.  If peak util >> 1.0 the bay is genuinely over-subscribed -> no
      packing can fit them at R -> must stagger in time or evict.
  (2) SLACK: deadline slack = due - (R+P).  If blocks have large slack, entries
      can be STAGGERED (scheduled later) without tardiness => keep them in the
      preferred bay (low z3) by sequencing, not eviction.  If slack ~0, staggering
      makes them late => eviction is the only z1 fix.

This decides the packer approach: dense 2D repack (low util, packing-wasteful)
vs schedule-first sequencing (high util + high slack) vs eviction is unavoidable
(high util + low slack).

  python notes/devlog/probe_packing_slack.py prob_3 prob_5 prob_12
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M          # noqa: E402
import fastfloor as FF           # noqa: E402
from utils import Bay            # noqa: E402


def min_bbox_area(blk):
    best = None
    for sh in blk.get("shape", []):
        xs = []; ys = []
        for layer in sh.get("layers", []):
            for (x, y) in layer:
                xs.append(x); ys.append(y)
        if xs:
            a = (max(xs) - min(xs)) * (max(ys) - min(ys))
            best = a if best is None else min(best, a)
    return best or 0


def probe(inst):
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json", encoding="utf-8"))
    blocks = prob["blocks"]
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    ba = [prob["bays"][j]["width"] * prob["bays"][j]["height"] for j in range(nb)]
    avg = sum(ba) / nb
    bay_u = [avg / a for a in ba]
    fbays = M._feasible_bays(blocks, bays)
    DUE = [int(b["due_date"]) for b in blocks]
    R = [int(b["release_time"]) for b in blocks]
    P = [int(b["processing_time"]) for b in blocks]

    assign = M._cpsat_assignment(prob, bays, fbays, bay_u, time_budget=10.0)
    if assign is None:
        print(f"{inst}: no assignment"); return
    members = [[] for _ in range(nb)]
    for b, j in enumerate(assign):
        members[j].append(b)
    edd = sorted(range(len(blocks)), key=lambda i: (DUE[i], R[i]))
    pos = {i: k for k, i in enumerate(edd)}

    print(f"\n=== {inst} ===")
    for j in range(nb):
        mem = members[j]
        if not mem:
            continue
        order = sorted(mem, key=lambda i: pos[i])
        res, ft = FF._fixed_time_decode(bays[j], j, mem, blocks, 9e18, order_key=order)
        tard = ft.get("ft_tard", 0) if ft else 9e9
        if tard <= 1e-9:
            continue
        # (1) peak co-present footprint utilization at entry=R
        evts = []
        for b in mem:
            evts.append((R[b], min_bbox_area(blocks[b])))
            evts.append((R[b] + P[b], -min_bbox_area(blocks[b])))
        evts.sort()
        cur = peak = 0
        for _t, d in evts:
            cur += d
            peak = max(peak, cur)
        util = peak / ba[j]
        # (2) deadline slack distribution
        slacks = sorted(DUE[b] - (R[b] + P[b]) for b in mem)
        med = slacks[len(slacks) // 2]
        n_tight = sum(1 for s in slacks if s <= 0)
        print(f"  bay{j}: {len(mem)} blk  ft_tard={tard:.0f}  forced={ft.get('forced')}  "
              f"peak_area_util={util:.2f}  slack[min/med/max]={slacks[0]}/{med}/{slacks[-1]}  "
              f"n_tight(slack<=0)={n_tight}")


if __name__ == "__main__":
    for a in sys.argv[1:]:
        probe(a)
