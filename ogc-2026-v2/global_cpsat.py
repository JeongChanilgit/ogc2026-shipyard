"""
global_cpsat.py — 전역 그리디 배정 + v2 패킹 + CP-SAT 타이밍 오라클 (사용자 설계).

  1) 전역 그리디 배정: 각 블록을 obj 최소 베이에 (w1·혼잡 + w2·Δz2 + w3·Δz3).
     z2·z3 는 배정만의 함수 → 배정으로 줄인다. z1 은 CP-SAT 타이밍이 레버.
  2) 베이별 v2 폴리곤 패킹 → 레이아웃 고정.
  3) `_cpsat_bay_timing_verified` (원래 솔버의 타이밍 오라클) 로 z1 최적 재타이밍.
  4) 원래 솔버(myalgorithm.algorithm)와 동일 인스턴스 비교.

실행: <env-python> global_cpsat.py 200 prob_38 prob_37
"""
from __future__ import annotations

import os

os.environ.setdefault("OGC_HYBRID_RESERVE_S", "1")

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))

import utils  # noqa: E402
from utils import Bay, check_feasibility  # noqa: E402
from baseline_greedy import _build_operations  # noqa: E402
from myalgorithm import _cpsat_bay_timing_verified, algorithm as orig_algorithm  # noqa: E402
from assign_search import build_set, z2, z3, SCALE  # noqa: E402
from temporal_pack import simulate, seed_order  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def _ops_sorted(flat):
    """flat 배치 → 시간키 오름차순 + EXIT-우선 operations dict (공식검증 통과 포맷)."""
    ops = {}
    for r in flat:
        et, xt = str(int(r["entry_time"])), str(int(r["exit_time"]))
        ops.setdefault(et, []).append({"type": "ENTRY", "block_id": r["block_id"],
                                       "bay_id": r["bay_id"], "x": r["x"], "y": r["y"],
                                       "orient_idx": r["orient_idx"]})
        ops.setdefault(xt, []).append({"type": "EXIT", "block_id": r["block_id"],
                                       "bay_id": r["bay_id"]})
    for t in ops:
        ops[t].sort(key=lambda o: 0 if o["type"] == "EXIT" else 1)
    return {k: ops[k] for k in sorted(ops, key=lambda s: int(s))}


def _obb(blk, o):
    xs = [p[0] for ly in blk["shape"][o]["layers"] for p in ly]
    ys = [p[1] for ly in blk["shape"][o]["layers"] for p in ly]
    return max(xs) - min(xs), max(ys) - min(ys)


def global_greedy_assign(data):
    """weight-adaptive 전역그리디: score = w1·tardy_est + w2·Δz2 + w3·Δz3 (CW 없음).

    z1 항 = area-time 혼잡 기반 지각 추정(시간 단위) → w1 이 인스턴스 가중을 자동 반영.
    한 베이에 i의 [release,due] 창과 겹치는 블록 footprint 합이 베이 면적을 넘으면
    그만큼 대기(wait) → 지각 추정. 고-w1 인스턴스는 혼잡 회피(분산), 고-w3는 선호 우선."""
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    m, N = len(bays), len(blocks)
    area = [bays[j]["width"] * bays[j]["height"] for j in range(m)]
    u = [(sum(area) / m) / a for a in area]
    fit, fa = [], []
    for i in range(N):
        bbs = [_obb(blocks[i], o) for o in range(len(blocks[i]["shape"]))]
        f = [j for j in range(m)
             if any(bw <= bays[j]["width"] + 1e-6 and bh <= bays[j]["height"] + 1e-6 for bw, bh in bbs)]
        fit.append(f or list(range(m)))
        fa.append(min(bw * bh for bw, bh in bbs) * 0.78)   # footprint 근사(오목 ~78%)
    load = [0.0] * m
    win = [[] for _ in range(m)]      # 베이별 (R, D, footprint)

    def z2_of(loads):
        wl = [u[j] * loads[j] for j in range(m)]
        return max(wl) - min(wl)

    assign = [0] * N
    order = sorted(range(N), key=lambda i: blocks[i]["due_date"])
    for i in order:
        R = blocks[i].get("release_time", 0)
        D = blocks[i]["due_date"]
        P = blocks[i]["processing_time"]
        pr = blocks[i]["bay_preferences"]
        smax = max(pr)
        wk = blocks[i].get("workload", 0)
        best = None
        for j in fit[i]:
            ov = sum(b for (bR, bD, b) in win[j] if bR < D and R < bD)   # 창 겹침 footprint
            util = (ov + fa[i]) / area[j]
            wait = max(0.0, util - 1.0) * max(1.0, D - R)     # 과적분 → 대기
            tardy_est = max(0.0, R + wait + P - D)
            nl = load[:]
            nl[j] += wk
            dz2 = z2_of(nl) - z2_of(load)
            dz3 = smax - pr[j]
            sc = w1 * tardy_est + w2 * dz2 + w3 * dz3
            if best is None or sc < best[0]:
                best = (sc, j)
        j = best[1]
        assign[i] = j
        load[j] += wk
        win[j].append((R, D, fa[i]))
    return assign


def our_pipeline(data, tl):
    bays, blocks = data["bays"], data["blocks"]
    m = len(bays)
    t0 = time.time()
    assign = global_greedy_assign(data)
    results, flat = {}, []
    for j in range(m):
        ids = [i for i in range(len(blocks)) if assign[i] == j]
        if not ids:
            continue
        W, H = bays[j]["width"], bays[j]["height"]
        sub = build_set(blocks, W, H, ids, SCALE)
        placed, _ = simulate(sub, seed_order(sub, "edd"), allow_stack=True)
        results[j] = {}
        for p in placed:
            rec = {"block_id": p["id"], "bay_id": j, "x": int(p["x"]), "y": int(p["y"]),
                   "orient_idx": int(p["orient"]), "entry_time": int(p["entry"]),
                   "exit_time": int(p["exit"])}
            results[j][p["id"]] = rec
            flat.append(rec)
    init = check_feasibility(data, {"operations": _ops_sorted(flat)})
    if not init.get("feasible"):
        print(f"  [init INFEASIBLE stage={init.get('stage')}: {(init.get('violations') or [])[:2]}]", flush=True)
    best_sol, best = {"operations": _ops_sorted(flat)}, init
    # CP-SAT 타이밍 오라클
    bays_objs = [Bay.from_dict(bays[j], j) for j in range(m)]
    try:
        cand = _cpsat_bay_timing_verified(data, bays_objs, results,
                                          deadline=time.monotonic() + tl * 0.6)
        if cand is not None:
            c = check_feasibility(data, cand)
            if c.get("feasible") and (not best.get("feasible")
                                      or c["objective"] < best["objective"]):
                best_sol, best = cand, c
    except Exception as e:
        print(f"  [oracle 에러 {e}]", flush=True)
    return best, init, time.time() - t0


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 200.0
    names = sys.argv[2:] or ["prob_38", "prob_37", "prob_25", "prob_40"]
    print(f"== H1': weight-adaptive 전역그리디 + v2 + CP-SAT vs 원래 (@{tl}s) ==", flush=True)
    wins = 0
    for nm in names:
        data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
        og = check_feasibility(data, orig_algorithm(data, tl))
        ours, init, dt = our_pipeline(data, tl)
        print(f"\n[{nm}] N={len(data['blocks'])}, {len(data['bays'])}bays, w={data['weights']}", flush=True)
        print(f"  {'원래':<14} obj={og.get('objective'):>14,.0f}  z1={og.get('obj1')}  z2={og.get('obj2')}  z3={og.get('obj3')}", flush=True)
        o = ours.get("objective")
        if o is None:
            print(f"  {'우리(WA)':<14} infeasible (init feas={init.get('feasible')}, stage={init.get('stage')})", flush=True)
            continue
        d = og["objective"] - o
        if d > 0:
            wins += 1
        print(f"  {'우리(WA)':<14} obj={o:>14,.0f}  z1={ours.get('obj1')}  z2={ours.get('obj2')}  z3={ours.get('obj3')}"
              f"  => {'승' if d > 0 else '패'} {d/og['objective']*100:+.1f}%  ({dt:.0f}s)", flush=True)
    print(f"\n승 {wins}/{len(names)}", flush=True)


if __name__ == "__main__":
    main()
