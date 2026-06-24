"""
validate_official.py — 우리 해를 *공식* src/utils.check_feasibility 로 검증.

우리 배정 + 베이별 temporal 스케줄 → operations dict 조립 → 공식 체커 호출.
공식 {feasible, stage, objective, obj1/2/3} vs 우리 내부 추정 비교.

실행: <env-python> validate_official.py [instance]   (기본 prob_29, everyone-preferred)
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))   # 공식 utils

import utils  # noqa: E402  (src/utils.py)
from assign_search import build_set, z2, z3, SCALE  # noqa: E402
from temporal_pack import simulate, seed_order  # noqa: E402


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        THIS, "..", "instances", "train", "prob_29.json")
    data = json.load(open(inst, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    N, m = len(blocks), len(bays)
    dims = [(b["width"], b["height"]) for b in bays]
    areas = [W * H for (W, H) in dims]
    u = [(sum(areas) / m) / a for a in areas]

    # fit-aware everyone-to-preferred
    def _obb(blk, o):
        xs = [p[0] for ly in blk["shape"][o]["layers"] for p in ly]
        ys = [p[1] for ly in blk["shape"][o]["layers"] for p in ly]
        return max(xs) - min(xs), max(ys) - min(ys)
    assign = []
    for i in range(N):
        bbs = [_obb(blocks[i], o) for o in range(len(blocks[i]["shape"]))]
        feas = [j for j in range(m)
                if any(bw <= dims[j][0] + 1e-6 and bh <= dims[j][1] + 1e-6 for bw, bh in bbs)]
        feas = feas or list(range(m))
        assign.append(max(feas, key=lambda j: blocks[i]["bay_preferences"][j]))

    # 베이별 스케줄 → operations
    ops = {}
    internal_z1 = 0
    for j in range(m):
        ids = [i for i in range(N) if assign[i] == j]
        if not ids:
            continue
        sub = build_set(blocks, dims[j][0], dims[j][1], ids, SCALE)
        placed, z1 = simulate(sub, seed_order(sub, "edd"), allow_stack=True)
        internal_z1 += z1
        for p in placed:
            et, xt = str(int(p["entry"])), str(int(p["exit"]))
            ops.setdefault(et, []).append(
                {"type": "ENTRY", "block_id": int(p["id"]), "bay_id": j,
                 "x": int(p["x"]), "y": int(p["y"]), "orient_idx": int(p["orient"])})
            ops.setdefault(xt, []).append(
                {"type": "EXIT", "block_id": int(p["id"]), "bay_id": j})
    for t in ops:                       # 같은 시각 EXIT 먼저
        ops[t].sort(key=lambda o: 0 if o["type"] == "EXIT" else 1)

    # --- 진단 ---
    ent = [o["block_id"] for t in ops for o in ops[t] if o["type"] == "ENTRY"]
    ext = [o["block_id"] for t in ops for o in ops[t] if o["type"] == "EXIT"]
    print(f"[diag] ENTRY ops={len(ent)} (unique {len(set(ent))}), "
          f"EXIT ops={len(ext)} (unique {len(set(ext))}), N={N}")
    miss = sorted(set(ent) - set(ext))
    dup = sorted(b for b in set(ent) if ent.count(b) > 1)
    print(f"[diag] ENTRY 있고 EXIT 없는 블록: {miss[:15]} (총 {len(miss)})")
    print(f"[diag] ENTRY 중복 블록: {dup[:15]} (총 {len(dup)})")

    internal_z2 = z2(assign, blocks, u, m)
    internal_z3 = z3(assign, blocks)
    internal_obj = w1 * internal_z1 + w2 * internal_z2 + w3 * internal_z3

    print(f"== 공식 검증 : {os.path.basename(inst)} (everyone-feasible-preferred) ==")
    print(f"   블록 {N}, 베이 {m}, ops 시각 {len(ops)}개\n")
    print(f"우리 내부추정: obj={internal_obj:,.0f}  Z1={internal_z1} Z2={internal_z2:.0f} Z3={internal_z3}\n")

    # 공식 체커는 dict 삽입순서로 순회 → 시간 오름차순 정렬 필수 (ENTRY가 EXIT보다 먼저)
    ops_sorted = {k: ops[k] for k in sorted(ops, key=lambda s: int(s))}

    for bid in (43, 57, 149, 107):
        for k, opl in ops_sorted.items():
            for idx, o in enumerate(opl):
                if o["block_id"] == bid:
                    nl = len(blocks[bid]["shape"][o.get("orient_idx", 0)]["layers"])
                    print(f"[diag] block {bid}: {o['type']} t={k} bay={o['bay_id']} "
                          f"idx={idx}/{len(opl)} layers={nl}")
    res = utils.check_feasibility(data, {"operations": ops_sorted})
    print("── 공식 utils.check_feasibility ──")
    print(f"  feasible = {res.get('feasible')}")
    print(f"  stage    = {res.get('stage')}")
    if res.get("violations"):
        print(f"  violations(앞 5): {res['violations'][:5]}")
    print(f"  objective= {res.get('objective')}")
    print(f"  obj1(Z1) = {res.get('obj1')}")
    print(f"  obj2(Z2) = {res.get('obj2')}")
    print(f"  obj3(Z3) = {res.get('obj3')}")

    if res.get("feasible"):
        off = res.get("objective")
        print(f"\n=> 공식 feasible! 공식 obj={off:,.0f} vs 내부 {internal_obj:,.0f} "
              f"(차이 {abs(off-internal_obj):,.0f})")
    else:
        print(f"\n=> 공식 INFEASIBLE (stage {res.get('stage')}). 우리 내부검증이 못 잡은 위반.")


if __name__ == "__main__":
    main()
