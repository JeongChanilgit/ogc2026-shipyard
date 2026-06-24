"""Probe: can a smarter placement ORDER pack the zero-slack-at-R blocks denser
(lower ft_tard) than EDD?  Cheap test before building a full repositioning nester.

Orders tried per congested bay:
  EDD            due, release          (current default)
  SLACK_AREA     slack asc, area desc  (must-be-at-R first, big first = denser BL)
  AREA_DESC      area desc             (classic BL packing)
  TIGHT_FIRST    (slack<=0 first by area desc) then (slack>0 by EDD)
  + best-of random shuffles

  python notes/devlog/probe_order.py prob_3 prob_5 prob_12
"""
import json
import random
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
    DUE = [int(b["due_date"]) for b in blocks]; R = [int(b["release_time"]) for b in blocks]
    P = [int(b["processing_time"]) for b in blocks]
    A = [min_bbox_area(b) for b in blocks]
    assign = M._cpsat_assignment(prob, bays, fbays, bay_u, time_budget=10.0)
    members = [[] for _ in range(nb)]
    for b, j in enumerate(assign):
        members[j].append(b)

    def tard(j, order):
        res, ft = FF._fixed_time_decode(bays[j], j, members[j], blocks, 9e18, order_key=order)
        return ft.get("ft_tard", 9e9) if ft else 9e9

    print(f"\n=== {inst} ===")
    rng = random.Random(0)
    for j in range(nb):
        mem = members[j]
        if not mem:
            continue
        edd = sorted(mem, key=lambda i: (DUE[i], R[i]))
        t_edd = tard(j, edd)
        if t_edd <= 1e-9:
            continue
        orders = {
            "EDD": edd,
            "SLACK_AREA": sorted(mem, key=lambda i: (DUE[i] - R[i] - P[i], -A[i])),
            "AREA_DESC": sorted(mem, key=lambda i: -A[i]),
            "TIGHT_FIRST": sorted(mem, key=lambda i: (0 if DUE[i]-R[i]-P[i] <= 0 else 1,
                                                      DUE[i]-R[i]-P[i], -A[i])),
        }
        best_named = min(orders, key=lambda k: tard(j, orders[k]))
        best_t = tard(j, orders[best_named])
        # best-of random shuffles
        rt = best_t
        for _ in range(30):
            sh = mem[:]; rng.shuffle(sh)
            rt = min(rt, tard(j, sh))
        print(f"  bay{j} ({len(mem)} blk): EDD={t_edd:.0f}  "
              + "  ".join(f"{k}={tard(j,orders[k]):.0f}" for k in orders)
              + f"  best_rand30={rt:.0f}")


if __name__ == "__main__":
    for a in sys.argv[1:]:
        probe(a)
