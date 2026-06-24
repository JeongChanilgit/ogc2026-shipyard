"""
solve_official.py — 시간예산 안에서 도는 v2 솔버 + 공식 검증.

파이프라인: fit-aware 배정 → toss(시간예산) → 베이별 temporal 스케줄(공식 게이트) →
operations dict → 공식 utils.check_feasibility 로 진짜 obj 확정.

실행: <env-python> solve_official.py 120 prob_21 prob_25
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))

import utils  # noqa: E402
from utils import Bay  # noqa: E402
from myalgorithm import _cpsat_bay_timing_verified, algorithm as _orig_alg  # noqa: E402
from assign_search import build_set, _z1_job, z2, z3, SCALE  # noqa: E402,F401
from temporal_pack import simulate, seed_order  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
TOPK = 14


def _build_ops(assign, blocks, dims, m):
    """최종 배정으로 베이별 스케줄 → (ops_sorted, internal_z1, results{bay:{bid:rec}})."""
    ops, iz1, results = {}, 0, {}
    for j in range(m):
        ids = [i for i in range(len(blocks)) if assign[i] == j]
        if not ids:
            continue
        sub = build_set(blocks, dims[j][0], dims[j][1], ids, SCALE)
        placed, z1 = simulate(sub, seed_order(sub, "edd"), allow_stack=True)
        iz1 += z1
        results[j] = {}
        for p in placed:
            rec = {"block_id": int(p["id"]), "bay_id": j, "x": int(p["x"]),
                   "y": int(p["y"]), "orient_idx": int(p["orient"]),
                   "entry_time": int(p["entry"]), "exit_time": int(p["exit"])}
            results[j][int(p["id"])] = rec
            et, xt = str(int(p["entry"])), str(int(p["exit"]))
            ops.setdefault(et, []).append(
                {"type": "ENTRY", "block_id": int(p["id"]), "bay_id": j,
                 "x": int(p["x"]), "y": int(p["y"]), "orient_idx": int(p["orient"])})
            ops.setdefault(xt, []).append(
                {"type": "EXIT", "block_id": int(p["id"]), "bay_id": j})
    for t in ops:
        ops[t].sort(key=lambda o: 0 if o["type"] == "EXIT" else 1)
    ops_sorted = {k: ops[k] for k in sorted(ops, key=lambda s: int(s))}
    return ops_sorted, iz1, results


def solve_official(inst, timelimit):
    t0 = time.time()
    data = json.load(open(inst, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    N, m = len(blocks), len(bays)
    dims = [(b["width"], b["height"]) for b in bays]
    areas = [W * H for (W, H) in dims]
    u = [(sum(areas) / m) / a for a in areas]

    def _obb(blk, o):
        xs = [p[0] for ly in blk["shape"][o]["layers"] for p in ly]
        ys = [p[1] for ly in blk["shape"][o]["layers"] for p in ly]
        return max(xs) - min(xs), max(ys) - min(ys)
    fit = []
    for i in range(N):
        bbs = [_obb(blocks[i], o) for o in range(len(blocks[i]["shape"]))]
        f = {j for j in range(m)
             if any(bw <= dims[j][0] + 1e-6 and bh <= dims[j][1] + 1e-6 for bw, bh in bbs)}
        fit.append(f or set(range(m)))
    assign = [max(fit[i], key=lambda j: blocks[i]["bay_preferences"][j]) for i in range(N)]

    z1cache, tardycache = {}, {}

    def get_z1(W, H, ids):
        k = (W, H, ids)
        if k not in z1cache:
            _, z, t = _z1_job((inst, W, H, ids))
            z1cache[k], tardycache[k] = z, t
        return z1cache[k]

    def bay_ids(asg):
        return {j: tuple(sorted(i for i in range(N) if asg[i] == j)) for j in range(m)}

    budget = timelimit * 0.75       # toss 예산 (나머지는 최종 스케줄+검증)
    ex = ProcessPoolExecutor(max_workers=4)
    moves = 0
    while time.time() - t0 < budget and moves < 200:
        bi = bay_ids(assign)
        z1_by = {j: get_z1(dims[j][0], dims[j][1], bi[j]) for j in range(m)}
        bott = max(range(m), key=lambda j: z1_by[j])
        if z1_by[bott] == 0:
            break
        tl = tardycache[(dims[bott][0], dims[bott][1], bi[bott])]
        tardy = sorted([(e, x - d) for (e, x, d) in tl if x - d > 0], key=lambda z: -z[1])[:TOPK]
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

    ops, iz1, results = _build_ops(assign, blocks, dims, m)
    iz2, iz3 = z2(assign, blocks, u, m), z3(assign, blocks)
    internal = w1 * iz1 + w2 * iz2 + w3 * iz3
    res = utils.check_feasibility(data, {"operations": ops})
    # CP-SAT 타이밍 오라클: 레이아웃 고정, z1 최적 재타이밍 (z2/z3 불변)
    cpsat = False
    try:
        bays_objs = [Bay.from_dict(bays[j], j) for j in range(m)]
        cand = _cpsat_bay_timing_verified(
            data, bays_objs, results, deadline=t0 + timelimit * 0.97)
        if cand is not None:
            c = utils.check_feasibility(data, cand)
            if c.get("feasible") and (not res.get("feasible")
                                      or c["objective"] < res.get("objective", 1e18)):
                res, cpsat = c, True
    except Exception:
        pass
    cnt = [sum(1 for j in assign if j == k) for k in range(m)]
    return {"inst": os.path.basename(inst), "N": N, "m": m,
            "feasible": res.get("feasible"), "stage": res.get("stage"),
            "official_obj": res.get("objective"), "internal_obj": internal,
            "obj1": res.get("obj1"), "obj2": res.get("obj2"), "obj3": res.get("obj3"),
            "moves": moves, "dist": cnt, "t": time.time() - t0, "cpsat": cpsat,
            "viol": (res.get("violations") or [])[:2]}


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    names = sys.argv[2:] or ["prob_38", "prob_37", "prob_25", "prob_40"]
    print(f"== H2: toss배정 + v2패킹 + CP-SAT 타이밍 vs 원래 (@{tl}s) : {', '.join(names)} ==", flush=True)
    wins = 0
    for nm in names:
        path = os.path.join(TRAIN, nm + ".json")
        r = solve_official(path, tl)
        import json as _j
        data = _j.load(open(path, encoding="utf-8"))
        og = utils.check_feasibility(data, _orig_alg(data, tl))
        oo = r["official_obj"]
        print(f"\n[{nm}] N={r['N']}, {r['m']}bays, w={data['weights']}", flush=True)
        print(f"  원래       obj={og.get('objective'):>14,.0f}  z1={og.get('obj1')} z2={og.get('obj2')} z3={og.get('obj3')}", flush=True)
        if oo is None:
            print(f"  우리(H2)   INFEASIBLE stage={r['stage']} {r['viol']}", flush=True)
            continue
        d = og["objective"] - oo
        if d > 0:
            wins += 1
        print(f"  우리(H2)   obj={oo:>14,.0f}  z1={r['obj1']} z2={r['obj2']} z3={r['obj3']}"
              f"  => {'승' if d > 0 else '패'} {d/og['objective']*100:+.1f}%  (cpsat={r['cpsat']}, toss{r['moves']}, {r['t']:.0f}s)", flush=True)
    print(f"\n승 {wins}/{len(names)}", flush=True)


if __name__ == "__main__":
    main()
