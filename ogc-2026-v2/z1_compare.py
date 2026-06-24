"""
z1_compare.py — AABB(원래) vs 폴리곤의 실제 Z1·목적함수 비교 (temporal 스케줄러).

같은 스케줄러·같은 EDD 순서, *기하만* 다름:
  AABB : 단층 바운딩박스 (옛 방식, 스택 없음)
  POLY : 실제 다층 폴리곤 (오목부 + overhang 스택 + exit가드)

배정 = 모두 최선호 베이(everyone-to-preferred). 그 배정에서:
  Z1 = Σ max(0, exit−due)  (베이별 temporal, 합산)
  Z2 = max_j u_j·load_j − min_j u_j·load_j   (배정만의 함수, 두 방식 동일)
  Z3 = 0  (전부 선호 베이 → S_max−S_assigned=0)
  obj = w1·Z1 + w2·Z2 + w3·Z3

실행: <env-python> z1_compare.py [instance]   (기본 prob_29)
주: 단일 베이 레벨 내부검증(충돌+크레인). 공식 utils 전체검증은 별도.
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from temporal_pack import build_subset, simulate, seed_order  # noqa: E402
from temporal_experiment import selfcheck  # noqa: E402


def run_bay(inst, bay, geom):
    sub = build_subset(inst, bay, SCALE, geom=geom)
    placed, z1 = simulate(sub, seed_order(sub, "edd"), allow_stack=(geom == "poly"))
    pl = [(p["id"], p["x"], p["y"], p["orient"], p["entry"], p["exit"]) for p in placed]
    ov, crane = selfcheck(sub, pl)
    feas = ov < 1e-6 and crane == 0
    return {"z1": z1, "n": len(placed), "of": len(sub["subset"]), "feas": feas,
            "ov": ov, "crane": crane}


SCALE = 2


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        THIS, "..", "instances", "train", "prob_29.json")
    data = json.load(open(inst, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    m = len(bays)
    pref = [max(range(m), key=lambda j: blocks[i]["bay_preferences"][j])
            for i in range(len(blocks))]

    # Z2 (배정만의 함수, 두 방식 동일) / Z3 = 0
    areas = [bays[j]["width"] * bays[j]["height"] for j in range(m)]
    avg = sum(areas) / m
    u = [avg / a for a in areas]
    load = [0.0] * m
    for i in range(len(blocks)):
        load[pref[i]] += blocks[i].get("workload", 0)
    weighted = [u[j] * load[j] for j in range(m)]
    z2 = max(weighted) - min(weighted)
    z3 = 0

    print(f"== AABB vs POLY 목적함수 : {os.path.basename(inst)} "
          f"(w1={w1}, w2={w2}, w3={w3}) ==")
    print(f"   배정=everyone-to-preferred, Z3=0, Z2={z2:.1f} (두 방식 공통)\n")

    print(f"{'베이':<5}{'선호':>6}   {'AABB Z1':>10}{'feas':>6}   {'POLY Z1':>10}{'feas':>6}")
    print("-" * 56)
    tot = {"aabb": 0, "poly": 0}
    t0 = time.time()
    for j in range(m):
        if pref.count(j) == 0:
            continue
        a = run_bay(inst, j, "aabb")
        p = run_bay(inst, j, "poly")
        tot["aabb"] += a["z1"]
        tot["poly"] += p["z1"]
        fa = "OK" if a["feas"] else "X"
        fp = "OK" if p["feas"] else "X"
        print(f"{j:<5}{p['of']:>6}   {a['z1']:>10}{fa:>6}   {p['z1']:>10}{fp:>6}")
    print("-" * 56)
    print(f"{'합계 Z1':<11}   {tot['aabb']:>10}        {tot['poly']:>10}   "
          f"({time.time()-t0:.1f}s)\n")

    obj_a = w1 * tot["aabb"] + w2 * z2 + w3 * z3
    obj_p = w1 * tot["poly"] + w2 * z2 + w3 * z3
    print(f"목적함수 obj = w1·Z1 + w2·Z2 + w3·Z3")
    print(f"  AABB : {w1}·{tot['aabb']} + {w2}·{z2:.0f} + 0 = {obj_a:,.0f}")
    print(f"  POLY : {w1}·{tot['poly']} + {w2}·{z2:.0f} + 0 = {obj_p:,.0f}")
    if obj_a:
        print(f"\n=> POLY 가 AABB 대비 obj {obj_a-obj_p:,.0f} 감소 "
              f"({(1-obj_p/obj_a)*100:.1f}%), 전부 Z1(−{tot['aabb']-tot['poly']})에서.")


if __name__ == "__main__":
    main()
