"""z3-recovery research tool (H1/H8/H10): start from box's best solution (z1≈0, z3 high),
move spilled blocks BACK to their preferred bay, accepting z1 rise while total z1 ≤ budget,
obj-gated, accurate (cells) re-pack of the touched bays. Goal: z1 ≤ comp_z1 AND z3 < comp_z3.

Usage: python notes/research/_z3recover.py <inst> [budget_mult] [tl]
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ["OGC_BOXDECOMP"] = "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import boxsolver as B  # noqa
from utils import Bay  # noqa

COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json",
                      encoding="utf-8"))["competitor"]


def run(inst, budget_mult=1.0, tl=40.0, allow_swaps=True):
    prob = json.load(open(ROOT / "instances" / "train" / f"{inst}.json", encoding="utf-8"))
    blocks = prob["blocks"]
    n = len(blocks)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
    nb = len(bays)
    B._winit(prob)
    w = prob["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    c = COMP[inst]
    budget = c["z1"] * budget_mult
    areas = [max(1.0, bays[j].width * bays[j].height) for j in range(nb)]
    avg = sum(areas) / nb
    u = [avg / a for a in areas]
    wl = [float(blocks[b]["workload"]) for b in range(n)]
    prefs = [blocks[b].get("bay_preferences", [0.0] * nb) for b in range(n)]
    smax = [max(prefs[b]) if prefs[b] else 0.0 for b in range(n)]

    sol = json.load(open(ROOT / "results" / "capture" / "box120_set2" / f"{inst}.json",
                         encoding="utf-8"))["solution"]
    bayof = {}
    for t, ops in sol["operations"].items():
        for o in ops:
            if o.get("type") == "ENTRY":
                bayof[o["block_id"]] = o["bay_id"]
    members = [set() for _ in range(nb)]
    for b in range(n):
        members[bayof.get(b, 0)].add(b)
    pref_bay = [max(range(nb), key=lambda j: prefs[b][j]) for b in range(n)]

    dl = time.monotonic() + tl
    _cache = {}

    def tard(j, mem):
        key = (j, frozenset(mem))
        if key in _cache:
            return _cache[key]
        if not mem:
            r = 0.0
        else:
            out, t = B._pack_one_cells(sorted(mem), blocks, bays[j], dl)
            r = t if out is not None else float("inf")
        _cache[key] = r
        return r

    def z2_of(loads):
        vals = [u[j] * loads[j] for j in range(nb)]
        import math
        return math.floor(max(vals) - min(vals)) if nb >= 2 else 0.0

    bt = [tard(j, members[j]) for j in range(nb)]
    loads = [sum(wl[b] for b in members[j]) for j in range(nb)]
    z1 = sum(bt)
    z3 = sum(smax[b] - prefs[b][bayof.get(b, 0)] for b in range(n))
    obj = w1 * z1 + w2 * z2_of(loads) + w3 * z3
    z1_0, z3_0, obj_0 = z1, z3, obj

    moves = 0
    while time.monotonic() < dl:
        best = None  # (new_obj, b, j_cur, j_pref, nt_src, nt_dst, new_z1)
        for b in range(n):
            j_cur = bayof[b]
            j_pref = pref_bay[b]
            if j_cur == j_pref:
                continue
            dev = smax[b] - prefs[b][j_cur]
            if dev <= 0:
                continue  # already best-pref among feasible
            nt_src = tard(j_cur, members[j_cur] - {b})
            nt_dst = tard(j_pref, members[j_pref] | {b})
            if nt_src == float("inf") or nt_dst == float("inf"):
                continue
            new_z1 = z1 - bt[j_cur] - bt[j_pref] + nt_src + nt_dst
            if new_z1 > budget + 1e-9:
                continue
            new_z3 = z3 - dev
            nl = loads[:]
            nl[j_cur] -= wl[b]
            nl[j_pref] += wl[b]
            new_obj = w1 * new_z1 + w2 * z2_of(nl) + w3 * new_z3
            if new_obj < obj - 1e-9 and (best is None or new_obj < best[0]):
                best = (new_obj, b, j_cur, j_pref, nt_src, nt_dst, new_z1, new_z3, nl)
        if best is None:
            break
        _, b, jc, jp, nts, ntd, new_z1, new_z3, nl = best
        members[jc].discard(b)
        members[jp].add(b)
        bayof[b] = jp
        bt[jc] = nts
        bt[jp] = ntd
        loads = nl
        z1, z3, obj = new_z1, new_z3, best[0]
        moves += 1

    print(f"{inst}: box(z1={z1_0:.0f},z3={z3_0:.0f},obj={obj_0:,.0f}) "
          f"-> recovered(z1={z1:.0f},z3={z3:.0f},obj={obj:,.0f}) "
          f"[{moves} moves]  comp(z1={c['z1']:.0f},z3={c['z3']:.0f},obj={c['obj']:,.0f})  "
          f"{'*** BEAT BOTH ***' if (z1 <= c['z1'] and z3 < c['z3']) else ('WIN-obj' if obj < c['obj'] else 'loss')}")


if __name__ == "__main__":
    inst = sys.argv[1] if len(sys.argv) > 1 else "prob_29"
    bm = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    tl = float(sys.argv[3]) if len(sys.argv) > 3 else 40.0
    run(inst, bm, tl)
