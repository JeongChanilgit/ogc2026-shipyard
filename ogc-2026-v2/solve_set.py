"""
solve_set.py — 현 파이프라인(폴리곤 밀도 + temporal + toss 배정)을 여러 인스턴스에 적용.

각 인스턴스: everyone-to-preferred 시작 → relocate toss(수렴/budget) → 내부 obj.
⚠ 내부 추정 obj (our temporal Z1, EDD, 베이 레벨). 공식 utils 미검증.

실행: <env-python> solve_set.py prob_21 prob_23 prob_25 prob_27 prob_39
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from assign_search import build_set, _z1_job, z2, z3, SCALE  # noqa: E402,F401

MAX_MOVES = 40
TOPK = 14
TRAIN = os.path.join(THIS, "..", "instances", "train")


def solve(inst):
    t0 = time.time()
    data = json.load(open(inst, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    N, m = len(blocks), len(bays)
    dims = [(b["width"], b["height"]) for b in bays]
    areas = [W * H for (W, H) in dims]
    avg = sum(areas) / m
    u = [avg / a for a in areas]

    def _obb(blk, o):
        xs = [p[0] for ly in blk["shape"][o]["layers"] for p in ly]
        ys = [p[1] for ly in blk["shape"][o]["layers"] for p in ly]
        return max(xs) - min(xs), max(ys) - min(ys)

    fit = [set() for _ in range(N)]   # 블록이 들어가는 베이만 배정 후보
    for i in range(N):
        bbs = [_obb(blocks[i], o) for o in range(len(blocks[i]["shape"]))]
        for j in range(m):
            W, H = dims[j]
            if any(bw <= W + 1e-6 and bh <= H + 1e-6 for (bw, bh) in bbs):
                fit[i].add(j)

    def _best_feasible(i):
        cs = [j for j in range(m) if j in fit[i]] or list(range(m))
        return max(cs, key=lambda j: blocks[i]["bay_preferences"][j])

    assign = [_best_feasible(i) for i in range(N)]

    z1cache, tardycache = {}, {}

    def get_z1(W, H, ids):
        k = (W, H, ids)
        if k not in z1cache:
            _, z, t = _z1_job((inst, W, H, ids))
            z1cache[k], tardycache[k] = z, t
        return z1cache[k]

    def bay_ids(asg):
        return {j: tuple(sorted(i for i in range(N) if asg[i] == j)) for j in range(m)}

    def OBJ(asg):
        bi = bay_ids(asg)
        z1 = sum(get_z1(dims[j][0], dims[j][1], bi[j]) for j in range(m))
        return w1 * z1 + w2 * z2(asg, blocks, u, m) + w3 * z3(asg, blocks), z1

    o0, z1_0 = OBJ(assign)
    ex = ProcessPoolExecutor(max_workers=4)
    moves = 0
    while moves < MAX_MOVES:
        bi = bay_ids(assign)
        z1_by = {j: get_z1(dims[j][0], dims[j][1], bi[j]) for j in range(m)}
        bott = max(range(m), key=lambda j: z1_by[j])
        if z1_by[bott] == 0:
            break
        tl = tardycache[(dims[bott][0], dims[bott][1], bi[bott])]
        tardy = sorted([(eid, e - d) for (eid, e, d) in tl if e - d > 0],
                       key=lambda x: -x[1])[:TOPK]
        if not tardy:
            break
        cand = [e for e, _ in tardy]
        jobs = {}
        for i in cand:
            jobs[(dims[bott][0], dims[bott][1], tuple(sorted(set(bi[bott]) - {i})))] = 1
            for tj in (j for j in range(m) if j != bott and j in fit[i]):
                jobs[(dims[tj][0], dims[tj][1], tuple(sorted(set(bi[tj]) | {i})))] = 1
        todo = [k for k in jobs if k not in z1cache]
        for key, z, t in ex.map(_z1_job, [(inst, k0, k1, k2) for (k0, k1, k2) in todo]):
            z1cache[key], tardycache[key] = z, t
        b2, b3 = z2(assign, blocks, u, m), z3(assign, blocks)
        best = None
        for i in cand:
            za = z1cache[(dims[bott][0], dims[bott][1], tuple(sorted(set(bi[bott]) - {i})))]
            for tj in (j for j in range(m) if j != bott and j in fit[i]):
                zb = z1cache[(dims[tj][0], dims[tj][1], tuple(sorted(set(bi[tj]) | {i})))]
                asg2 = list(assign)
                asg2[i] = tj
                d = (w1 * ((za + zb) - (z1_by[bott] + z1_by[tj]))
                     + w2 * (z2(asg2, blocks, u, m) - b2) + w3 * (z3(asg2, blocks) - b3))
                if best is None or d < best[0]:
                    best = (d, i, tj)
        if best is None or best[0] >= -1e-9:
            break
        _, i, tj = best
        assign[i] = tj
        moves += 1
    ex.shutdown()
    of, z1f = OBJ(assign)
    cnt = [sum(1 for j in assign if j == k) for k in range(m)]
    return {"inst": os.path.basename(inst), "N": N, "m": m, "base": o0,
            "final": of, "z1": z1f, "z2": z2(assign, blocks, u, m),
            "z3": z3(assign, blocks), "moves": moves, "dist": cnt,
            "w": (w1, w2, w3), "t": time.time() - t0}


def main():
    names = sys.argv[1:] or ["prob_21", "prob_23", "prob_25", "prob_27", "prob_39"]
    print(f"== 현 파이프라인 obj (내부추정) : {', '.join(names)} ==", flush=True)
    print(f"{'inst':<10}{'N':>4}{'bays':>5}{'w1':>8}  {'baseline':>14}{'final':>14}"
          f"{'  Z1':>8}{'Z3':>7}{'감소%':>7}{'시간':>7}", flush=True)
    print("-" * 95, flush=True)
    rows = []
    for nm in names:
        inst = os.path.join(TRAIN, nm + ".json")
        try:
            r = solve(inst)
            rows.append(r)
            print(f"{r['inst']:<10}{r['N']:>4}{r['m']:>5}{r['w'][0]:>8}  "
                  f"{r['base']:>14,.0f}{r['final']:>14,.0f}{r['z1']:>8}{r['z3']:>7}"
                  f"{(1-r['final']/r['base'])*100:>6.1f}%{r['t']:>6.0f}s  dist={r['dist']}",
                  flush=True)
        except Exception as e:
            import traceback
            print(f"{nm:<10} ERROR: {e}", flush=True)
            traceback.print_exc()
    if rows:
        tot = sum(r["final"] for r in rows)
        print("-" * 95, flush=True)
        print(f"합계 final obj (내부추정) = {tot:,.0f}", flush=True)


if __name__ == "__main__":
    main()
