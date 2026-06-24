"""EFFICIENT spill: each step, spill the block with the MAX z1-relief PER z3-cost
(own tardiness / z3 deviation cost) from the most-tardy bay → close z1 to 0 at the
LOWEST total z3. cheapest-z3 (curve2) keeps z3 low but floors z1=11; most-tardy
(curve3) closes z1 but over-spills z3=747. This greedy-optimal criterion should reach
z1=0 at z3 between them — target z3<432 ⇒ beat competitor on prob_13.

  STEPS=40 PACKTL=28 python notes/research/_spillcurve4.py prob_13
"""
import json
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as OA                      # noqa: E402
sys.path.insert(0, str(ROOT / "src"))
import boxsolver as BS                         # noqa: E402
from utils import Bay                          # noqa: E402

os.environ.setdefault("OGC_BD_CUMUL", "1")


def main():
    TARGET = (sys.argv[1:] or ["prob_13"])[0]
    STEPS = int(os.environ.get("STEPS", "40"))
    EVERY = int(os.environ.get("EVERY", "1"))
    PACKTL = float(os.environ.get("PACKTL", "28"))
    os.environ["OGC_BD_WORKERS"] = os.environ.get("BD_WORKERS", "4")
    COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json", encoding="utf-8"))["competitor"]
    HYB = json.load(open(ROOT / "notes" / "research" / "baselines" / "hybrid_set1.json"))
    prob = json.load(open(ROOT / "instances" / "train" / f"{TARGET}.json", encoding="utf-8"))
    blocks = prob["blocks"]; n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    cm = COMP.get(TARGET, {}); hy = HYB.get(TARGET, {})
    prefs = {b: blocks[b].get("bay_preferences", [0.0] * nb) for b in range(n)}
    smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
    fits = {b: BS._fits_per_bay(b, blocks[b], bays) for b in range(n)}
    geo = {b: BS._orient_bboxes(b, blocks[b]) for b in range(n)}
    due = {b: int(blocks[b]["due_date"]) for b in range(n)}

    def bbox_pack(mem, j):
        if not mem:
            return {}, 0.0
        order = sorted(mem, key=lambda b: (due[b], int(blocks[b]["release_time"])))
        out, t = BS._pack_one_bbox(order, blocks, bays[j], geo, time.monotonic() + 2.0)
        return (out or {}), (t if out is not None else math.inf)

    _, m0 = BS._assign_preferred(blocks, bays)
    members = [set(m) for m in m0]
    packs = [bbox_pack(members[j], j) for j in range(nb)]
    tard = [p[1] for p in packs]
    snaps = [[set(m) for m in members]]
    tabu = []
    for _step in range(1, STEPS + 1):
        if sum(tard) <= 0:
            break
        j = max(range(nb), key=lambda k: tard[k])
        out_j = packs[j][0]
        movable = [b for b in members[j] if any(k != j for k in fits[b])]
        mv = [b for b in movable if b not in tabu] or movable
        if not mv:
            break

        def score(b):
            relief = out_j.get(b, (0, 0, 0, 0, due[b]))[4] - due[b]   # own tardiness
            relief = max(0.0, relief)
            j2 = max((k for k in fits[b] if k != j), key=lambda k: prefs[b][k])
            z3cost = smax[b] - prefs[b][j2]
            return (relief + 1.0) / (z3cost + 1.0)                     # relief per z3

        b = max(mv, key=score)
        j2 = max((k for k in fits[b] if k != j), key=lambda k: prefs[b][k])
        members[j].discard(b); members[j2].add(b)
        packs[j] = bbox_pack(members[j], j); packs[j2] = bbox_pack(members[j2], j2)
        tard[j] = packs[j][1]; tard[j2] = packs[j2][1]
        tabu.append(b)
        if len(tabu) > nb * 2:
            tabu = tabu[nb:]
        snaps.append([set(m) for m in members])

    print(f"[{TARGET}] SPILL=efficient(relief/z3) | legacy obj={hy.get('obj')} z3={hy.get('z3')} | "
          f"comp obj={cm.get('obj')} z3={cm.get('z3')} | {len(snaps)} snaps PACKTL={PACKTL}", flush=True)
    print(f"{'k':>3}{'z1':>7}{'z2':>7}{'z3':>8}{'obj':>13}  res", flush=True)
    best = (math.inf, None)
    for k in range(0, len(snaps), EVERY):
        mem_lists = [list(m) for m in snaps[k]]
        r = BS._pack_members(mem_lists, bays, blocks, n, prob, time.monotonic() + PACKTL, "boxdecomp")
        if r is None:
            print(f"{k:>3}  infeasible", flush=True); continue
        o, sol = r
        feas, o2, z1, z2, z3 = OA.obj_tuple(prob, sol)
        tag = ("BEAT-COMP" if (cm.get("obj") and o2 < cm["obj"]) else
               ("beat-legacy" if (hy.get("obj") and o2 < hy["obj"]) else ""))
        if o2 < best[0]:
            best = (o2, k)
        print(f"{k:>3}{z1:>7.0f}{z2:>7.0f}{z3:>8.0f}{o2:>13.0f}  {tag}", flush=True)
    print(f"BEST obj={best[0]:.0f} at k={best[1]}", flush=True)


if __name__ == "__main__":
    main()
