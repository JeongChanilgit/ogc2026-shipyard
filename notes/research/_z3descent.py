"""Approach A, correctly seeded: start from the LEGACY z1=0 solution (its real
incumbent, z3 high) and descend z3 toward preferred using the ACCURATE cells oracle,
accepting only moves that keep z1=0 and lower total obj. The competitor proves a
z1=0 solution at LOWER z3 exists (prob_13: comp z3=432 vs legacy 805) — this tests
whether it's reachable by local z3-moves from legacy's incumbent.

  FS_TL=120 LEG_TL=120 python notes/research/_z3descent.py prob_13

Spawn-safe (real main-guarded file). Reuses boxsolver cells oracle + check_feasibility.
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
import myalgorithm as M                        # noqa: E402
from utils import Bay                          # noqa: E402


def members_from_sol(sol, n, nb):
    mem = [set() for _ in range(nb)]
    for t, ops in sol.get("operations", {}).items():
        for o in ops:
            if o.get("type") == "ENTRY":
                mem[int(o["bay_id"])].add(int(o["block_id"]))
    return mem


def main():
    TL = float(os.environ.get("FS_TL", "120"))       # descent budget
    LEG_TL = float(os.environ.get("LEG_TL", "120"))  # legacy seed budget
    targets = sys.argv[1:] or ["prob_13"]
    COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-15.json", encoding="utf-8"))["competitor"]
    HYB = json.load(open(ROOT / "notes" / "research" / "baselines" / "hybrid_set1.json"))
    for name in targets:
        prob = json.load(open(ROOT / "instances" / "train" / f"{name}.json", encoding="utf-8"))
        blocks = prob["blocks"]; n = len(blocks)
        bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
        nb = len(bays)
        hy = HYB.get(name, {}); cm = COMP.get(name, {})
        print(f"\n{name}: legacy obj={hy.get('obj')} z3={hy.get('z3')} | "
              f"comp obj={cm.get('obj')} z2={cm.get('z2')} z3={cm.get('z3')}", flush=True)

        # 1) legacy z1=0 seed
        os.environ["OGC_HYBRID"] = "0"
        t0 = time.monotonic()
        seed = M._legacy_algorithm(prob, LEG_TL)
        feas, o0, z10, z20, z30 = OA.obj_tuple(prob, seed)
        print(f"  legacy seed: obj={o0:.0f} z1={z10:.0f} z2={z20:.0f} z3={z30:.0f} "
              f"wall={time.monotonic()-t0:.1f}", flush=True)

        # 2) z3-descent with accurate cells oracle
        BS._FP_CACHE.clear()
        members = members_from_sol(seed, n, nb)
        prefs = {b: blocks[b].get("bay_preferences", [0.0] * nb) for b in range(n)}
        smax = {b: (max(prefs[b]) if prefs[b] else 0.0) for b in range(n)}
        fits = {b: BS._fits_per_bay(b, blocks[b], bays) for b in range(n)}
        wl = [float(blocks[b]["workload"]) for b in range(n)]
        areas = [max(1.0, bays[j].width * bays[j].height) for j in range(nb)]
        avg = sum(areas) / nb
        u = [avg / a for a in areas]
        w1 = prob.get("weights", {}).get("w1", 1.0)
        w2 = prob.get("weights", {}).get("w2", 1.0)
        w3 = prob.get("weights", {}).get("w3", 1.0)
        dl = time.monotonic() + TL
        _pc = {}

        def pc(j, mem):
            key = (j, frozenset(mem))
            r = _pc.get(key)
            if r is None:
                out, t = BS._pack_one_cells(sorted(mem), blocks, bays[j], dl) if mem else ({}, 0.0)
                r = t if out is not None else math.inf
                _pc[key] = r
            return r

        assign = {b: j for j in range(nb) for b in members[j]}
        tard = [pc(j, members[j]) for j in range(nb)]
        loads = [sum(wl[b] for b in members[j]) for j in range(nb)]

        def z2_of(ld):
            vals = [u[j] * ld[j] for j in range(nb)]
            return math.floor(max(vals) - min(vals)) if nb >= 2 else 0.0

        z1 = sum(tard); z3 = sum(smax[b] - prefs[b][assign[b]] for b in range(n))
        obj = w1 * z1 + w2 * z2_of(loads) + w3 * z3
        print(f"  seed (cells): z1={z1:.0f} z3={z3:.0f} obj~{obj:.0f}  (descending...)", flush=True)
        moves = 0
        while time.monotonic() < dl:
            # candidate moves: block to a MORE-preferred fitting bay (z3-reducing), best z3 gain first
            cands = []
            for b in range(n):
                j = assign[b]
                for j2 in fits[b]:
                    if j2 != j and prefs[b][j2] > prefs[b][j] + 1e-9:
                        cands.append((prefs[b][j2] - prefs[b][j], b, j, j2))
            cands.sort(reverse=True)
            applied = False
            for gain, b, j, j2 in cands[:200]:
                if time.monotonic() >= dl:
                    break
                ts = pc(j, members[j] - {b}); td = pc(j2, members[j2] | {b})
                if ts == math.inf or td == math.inf:
                    continue
                nz1 = z1 - tard[j] - tard[j2] + ts + td
                if nz1 > 1e-9:
                    continue                                  # keep z1=0
                nl = loads[:]; nl[j] -= wl[b]; nl[j2] += wl[b]
                dz3 = prefs[b][j] - prefs[b][j2]              # negative
                nobj = w1 * nz1 + w2 * z2_of(nl) + w3 * (z3 + dz3)
                if nobj < obj - 1e-9:
                    members[j].discard(b); members[j2].add(b); assign[b] = j2
                    tard[j] = ts; tard[j2] = td; loads = nl
                    z1 = nz1; z3 += dz3; obj = nobj; moves += 1; applied = True
                    break
            if not applied:
                break

        # 3) final exact pack + official obj
        mem_lists = [list(m) for m in members]
        best = None
        for fmode in ("cells", "cpsat"):
            r = BS._pack_members(mem_lists, bays, blocks, n, prob, time.monotonic() + 30, fmode)
            if r is not None and (best is None or r[0] < best[0]):
                best = r
        if best is None:
            print(f"  descent: moves={moves} but final pack INFEASIBLE", flush=True)
            continue
        fo, fsol = best
        feas, o, z1f, z2f, z3f = OA.obj_tuple(prob, fsol)
        tag = ("BEAT-COMP" if (cm.get("obj") and o < cm["obj"]) else
               ("beat-legacy" if o < o0 - 1 else ""))
        print(f"  AFTER descent: obj={o:.0f} z1={z1f:.0f} z2={z2f:.0f} z3={z3f:.0f} "
              f"moves={moves}  {tag}", flush=True)


if __name__ == "__main__":
    main()
