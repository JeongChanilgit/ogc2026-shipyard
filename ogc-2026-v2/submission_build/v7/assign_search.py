"""
assign_search.py — 배정/toss 층 (과적 베이 → 여유 베이로 재배정, 목적함수 최소화).

per-bay temporal 오라클(폴리곤+크레인+EDD) 위에 배정 결정을 얹는다:
  obj = w1·Σ_j Z1(bay j) + w2·Z2(배정) + w3·Z3(배정)
  Z1 = 베이별 temporal 스케줄(비싸다, 캐시) / Z2·Z3 = 배정만의 함수(싸다).

시작 = everyone-to-preferred. 그리디 relocate:
  병목 베이(w1·Z1 최대)의 *지각 블록*을 다른 베이로 옮겨보고, Δobj<0 면 채택.
  후보 이동 평가(=옮긴 두 베이 재스케줄)를 4코어 병렬. 개선 없을 때까지(또는 budget).

핵심: 블록을 빼면 그 베이 Z1 약하게 감소(공짜), 넣으면 약하게 증가 + Z3 비용.
실행: <env-python> assign_search.py [instance]
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from gridmap import build_shape  # noqa: E402
from density_pack import _common_masks  # noqa: E402
from temporal_pack import simulate, seed_order, descent  # noqa: E402

SCALE = 2
MAX_MOVES = 60      # 최대 toss 횟수 (수렴 시 조기 종료)
TOPK = 14           # 반복마다 평가할 지각 블록 수
POLISH_BUDGET = 30  # 베이별 순서 스왑탐색 시도 수
INST_GLOBAL = None  # worker 가 참조 (spawn 시 재설정)


def build_set(blocks, W, H, ids, scale):
    sub = {"W": W, "H": H, "scale": scale, "bay_id": -1, "subset": list(ids)}
    shapes, meta, cm = {}, {}, {}
    ml = 1
    for i in ids:
        shs = [build_shape(i, blocks[i], o, scale) for o in range(len(blocks[i]["shape"]))]
        shapes[i] = shs
        for s in shs:
            cm[id(s)] = _common_masks(s, scale)
            ml = max(ml, s.n_layers)
        meta[i] = (blocks[i].get("release_time", 0),
                   blocks[i].get("processing_time", 0),
                   blocks[i].get("due_date", 0))
    sub.update({"shapes": shapes, "meta": meta, "cm": cm, "max_layer": ml,
                "raw": {i: blocks[i] for i in ids}})
    return sub


def _z1_job(args):
    """worker: (inst, W, H, tuple(ids)) → (key, Z1, [(id,exit,due)...])."""
    inst, W, H, ids = args
    data = json.load(open(inst, encoding="utf-8"))
    blocks = data["blocks"]
    if not ids:
        return (args[1:], 0, [])
    sub = build_set(blocks, W, H, list(ids), SCALE)
    placed, z1 = simulate(sub, seed_order(sub, "edd"), allow_stack=True)
    tardy = [(p["id"], p["exit"], sub["meta"][p["id"]][2]) for p in placed]
    return ((W, H, ids), z1, tardy)


def z2(assign, blocks, u, m):
    load = [0.0] * m
    for i, j in enumerate(assign):
        load[j] += blocks[i].get("workload", 0)
    wl = [u[j] * load[j] for j in range(m)]
    return max(wl) - min(wl)


def z3(assign, blocks):
    s = 0
    for i, j in enumerate(assign):
        pr = blocks[i]["bay_preferences"]
        s += max(pr) - pr[j]
    return s


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        THIS, "..", "instances", "train", "prob_29.json")
    from concurrent.futures import ProcessPoolExecutor

    data = json.load(open(inst, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    N, m = len(blocks), len(bays)
    dims = [(bays[j]["width"], bays[j]["height"]) for j in range(m)]
    areas = [W * H for (W, H) in dims]
    avg = sum(areas) / m
    u = [avg / a for a in areas]

    assign = [max(range(m), key=lambda j: blocks[i]["bay_preferences"][j]) for i in range(N)]
    preferred = list(assign)
    prefs = [blocks[i]["bay_preferences"] for i in range(N)]

    def bay_ids(asg):
        return {j: tuple(sorted(i for i in range(N) if asg[i] == j)) for j in range(m)}

    # Z1 캐시 (key=(W,H,ids) → z1, tardy)
    z1cache, tardycache = {}, {}

    def get_z1(W, H, ids):
        k = (W, H, ids)
        if k not in z1cache:
            _, z, t = _z1_job((inst, W, H, ids))
            z1cache[k] = z
            tardycache[k] = t
        return z1cache[k]

    def obj(asg):
        bi = bay_ids(asg)
        z1 = sum(get_z1(dims[j][0], dims[j][1], bi[j]) for j in range(m))
        return w1 * z1 + w2 * z2(asg, blocks, u, m) + w3 * z3(asg, blocks), z1

    print(f"== 배정/toss 탐색 : {os.path.basename(inst)} "
          f"(w1={w1}, w2={w2}, w3={w3}) ==\n")
    o0, z1_0 = obj(assign)
    print(f"시작(everyone-to-preferred): obj={o0:,.0f}  (Z1={z1_0}, Z2={z2(assign,blocks,u,m):.0f}, Z3={z3(assign,blocks)})")

    ex = ProcessPoolExecutor(max_workers=4)
    t_start = time.time()
    moves = 0
    while moves < MAX_MOVES:
        bi = bay_ids(assign)
        z1_by = {j: get_z1(dims[j][0], dims[j][1], bi[j]) for j in range(m)}
        bott = max(range(m), key=lambda j: z1_by[j])          # 병목 = Z1 최대
        if z1_by[bott] == 0:
            break
        # 병목 베이의 지각 블록 (tardiness desc)
        tlist = tardycache[(dims[bott][0], dims[bott][1], bi[bott])]
        tardy = sorted([(eid, ex_ - due) for (eid, ex_, due) in tlist if ex_ - due > 0],
                       key=lambda x: -x[1])[:TOPK]
        if not tardy:
            break
        cand_ids = [eid for (eid, _) in tardy]
        targets = [j for j in range(m) if j != bott]

        # 평가할 고유 잡: 병목-블록제거 + 타깃-블록추가
        jobs = {}
        for i in cand_ids:
            rem = tuple(sorted(set(bi[bott]) - {i}))
            jobs[(dims[bott][0], dims[bott][1], rem)] = None
            for tj in targets:
                add = tuple(sorted(set(bi[tj]) | {i}))
                jobs[(dims[tj][0], dims[tj][1], add)] = None
        todo = [k for k in jobs if k not in z1cache]
        for (key, z, t) in ex.map(_z1_job, [(inst, k[0], k[1], k[2]) for k in todo]):
            z1cache[key] = z
            tardycache[key] = t

        # 최적 이동 선택
        base_z2 = z2(assign, blocks, u, m)
        base_z3 = z3(assign, blocks)
        best = None  # (Δobj, i, tj)
        for i in cand_ids:
            a = bott
            rem = tuple(sorted(set(bi[a]) - {i}))
            z1a2 = z1cache[(dims[a][0], dims[a][1], rem)]
            for tj in targets:
                add = tuple(sorted(set(bi[tj]) | {i}))
                z1b2 = z1cache[(dims[tj][0], dims[tj][1], add)]
                asg2 = list(assign)
                asg2[i] = tj
                dz1 = (z1a2 + z1b2) - (z1_by[a] + z1_by[tj])
                dz2 = z2(asg2, blocks, u, m) - base_z2
                dz3 = z3(asg2, blocks) - base_z3
                dobj = w1 * dz1 + w2 * dz2 + w3 * dz3
                if best is None or dobj < best[0]:
                    best = (dobj, i, tj)
        if best is None or best[0] >= -1e-9:
            print(f"  (개선 이동 없음 → 종료, {moves} moves)")
            break
        _, i, tj = best
        assign[i] = tj
        moves += 1
        o_now, z1_now = obj(assign)
        print(f"  move {moves}: 블록 {i}  bay{bott}→bay{tj}  "
              f"Δobj={best[0]:,.0f}  obj={o_now:,.0f} (Z1={z1_now})")
    of, z1f = obj(assign)
    print(f"\ntoss 후: obj={of:,.0f} (Z1={z1f}, Z2={z2(assign,blocks,u,m):.0f}, Z3={z3(assign,blocks)})")
    print(f"   obj {o0:,.0f} → {of:,.0f}  (−{o0-of:,.0f}, {(1-of/o0)*100:.1f}%), "
          f"{moves} toss, {time.time()-t_start:.0f}s")

    # --- SWAP 단계: displaced 블록을 선호 베이의 블록과 교환 (Z3↓, 부하/Z1 유지) ---
    print("\nSWAP 단계 (선호 베이로 교환)...")
    sw = 0
    while sw < 20:
        bi = bay_ids(assign)
        z1_by = {j: get_z1(dims[j][0], dims[j][1], bi[j]) for j in range(m)}
        cands = []
        for i in range(N):
            a, p = assign[i], preferred[i]
            if a == p:
                continue
            for k in bi[p]:
                est = (prefs[i][a] - prefs[i][p]) + (prefs[k][p] - prefs[k][a])
                cands.append((est, i, k, a, p))
        cands.sort(key=lambda c: c[0])
        cands = cands[:30]
        if not cands:
            break
        jobs = {}
        for (_e, i, k, a, p) in cands:
            sa = tuple(sorted((set(bi[a]) - {i}) | {k}))
            sp = tuple(sorted((set(bi[p]) - {k}) | {i}))
            jobs[(dims[a][0], dims[a][1], sa)] = None
            jobs[(dims[p][0], dims[p][1], sp)] = None
        todo = [key for key in jobs if key not in z1cache]
        for (key, z, t) in ex.map(_z1_job, [(inst, k0, k1, k2) for (k0, k1, k2) in todo]):
            z1cache[key] = z
            tardycache[key] = t
        base2, base3 = z2(assign, blocks, u, m), z3(assign, blocks)
        best = None
        for (_e, i, k, a, p) in cands:
            sa = tuple(sorted((set(bi[a]) - {i}) | {k}))
            sp = tuple(sorted((set(bi[p]) - {k}) | {i}))
            z1a2 = z1cache[(dims[a][0], dims[a][1], sa)]
            z1p2 = z1cache[(dims[p][0], dims[p][1], sp)]
            asg2 = list(assign)
            asg2[i], asg2[k] = p, a
            dobj = (w1 * ((z1a2 + z1p2) - (z1_by[a] + z1_by[p]))
                    + w2 * (z2(asg2, blocks, u, m) - base2)
                    + w3 * (z3(asg2, blocks) - base3))
            if best is None or dobj < best[0]:
                best = (dobj, i, k, a, p)
        if best is None or best[0] >= -1e-9:
            print(f"  (개선 교환 없음 → 종료, {sw} swaps)")
            break
        _, i, k, a, p = best
        assign[i], assign[k] = p, a
        sw += 1
        o_now, z1_now = obj(assign)
        print(f"  swap {sw}: 블록{i}(bay{a}→{p}) ↔ 블록{k}(bay{p}→{a})  "
              f"Δobj={best[0]:,.0f}  obj={o_now:,.0f} (Z1={z1_now})")

    ex.shutdown()
    of, z1f = obj(assign)
    print(f"\nSWAP 후: obj={of:,.0f} (Z1={z1f}, Z2={z2(assign,blocks,u,m):.0f}, Z3={z3(assign,blocks)})")

    # --- 순서 폴리시: 베이별 진입순서 스왑탐색으로 Z1 추가 절감 (EDD→best) ---
    print("\n순서 폴리시 (베이별 EDD→스왑탐색)...")
    bi = bay_ids(assign)
    z1_pol = 0
    for j in range(m):
        ids = list(bi[j])
        if not ids:
            continue
        edd_z1 = get_z1(dims[j][0], dims[j][1], bi[j])
        sub = build_set(blocks, dims[j][0], dims[j][1], ids, SCALE)
        r = descent(sub, seed_order(sub, "edd"), True, POLISH_BUDGET, 7000 + j)
        z1_pol += r["z1"]
        print(f"   bay{j}: Z1 {edd_z1} → {r['z1']}  ({len(ids)} blocks)")
    obj_pol = w1 * z1_pol + w2 * z2(assign, blocks, u, m) + w3 * z3(assign, blocks)
    print(f"\n폴리시 후: obj={obj_pol:,.0f} (Z1={z1_pol})")

    final = min(of, obj_pol)
    print(f"\n=> 최종 obj {o0:,.0f} → {final:,.0f}  "
          f"(−{o0-final:,.0f}, {(1-final/o0)*100:.1f}%)")
    cnt = [sum(1 for j in assign if j == k) for k in range(m)]
    print(f"   배정 분포: " + ", ".join(f"bay{k}={cnt[k]}" for k in range(m)))


if __name__ == "__main__":
    main()
