"""
copresence_diag.py -- 크로스베이 co-presence 잠재력 진단 (set2: prob_21..40)

배경: z1 = 구조적 co-presence.
  같은 베이에서 시간 구간이 겹치는 블록이 크레인 j>=k 제약으로 직렬화 -> tardiness 발생.
  피크 시점에 다른 베이가 한가하다면 -> 크로스베이 이동으로 피크를 낮출 수 있음.

주의: real_prob_*.json = 현재 솔버가 만든 '실제 해'. 이를 바탕으로 co-presence 구조 진단.
(make_seed 보다 더 현실적인 배정 분포를 보여줌.)

실행:
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe copresence_diag.py
"""

import json
import os
import sys
from collections import defaultdict

# -----------------------------------------------------------------------
# 경로 설정 — utils.py (v4) 사용
V4 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, V4)

import utils as _utils  # noqa: E402


# -----------------------------------------------------------------------
# 상수
CONGESTION_THR = 3   # co-presence >= 이 값이면 '혼잡'
SLACK_THR = 1        # co-presence <= 이 값이면 '한가'
SET2_RANGE = range(21, 41)  # prob_21..40


# -----------------------------------------------------------------------
def load_instance_and_solution(prob_num: int):
    """인스턴스 + 기존 솔버 해(real_prob_*.json) 로드."""
    inst_path = (
        f"C:/claude-develop/OGC2026/instances/train/prob_{prob_num}.json"
    )
    sol_path = os.path.join(V4, f"real_prob_{prob_num}.json")
    data = json.load(open(inst_path, encoding="utf-8"))
    sol = json.load(open(sol_path, encoding="utf-8"))
    return data, sol


def extract_placed(data: dict, sol: dict):
    """solution -> {bay_id: [{id, entry, exit, due, pref_bay, release}]}."""
    blocks = data["blocks"]
    ops = sol["operations"]

    entry_info: dict[int, dict] = {}
    exit_time: dict[int, int] = {}

    for t_str, op_list in ops.items():
        t = int(t_str)
        for op in op_list:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                entry_info[bid] = {
                    "bay_id": int(op["bay_id"]),
                    "entry": t,
                }
            elif op["type"] == "EXIT":
                exit_time[bid] = t

    bays: dict[int, list] = {}
    m = len(data["bays"])

    for bid, info in entry_info.items():
        j = info["bay_id"]
        entry = info["entry"]
        exit_t = exit_time.get(bid, entry + blocks[bid]["processing_time"])
        due = blocks[bid]["due_date"]
        release = blocks[bid]["release_time"]
        # preferred bay = argmax bay_preferences
        pref = max(range(m), key=lambda jj: blocks[bid]["bay_preferences"][jj])

        rec = {
            "id": bid,
            "bay": j,
            "entry": entry,
            "exit": exit_t,
            "due": due,
            "release": release,
            "pref": pref,
            "tardiness": max(0, exit_t - due),
        }
        bays.setdefault(j, []).append(rec)

    return bays


def copresence_profile(placed_list: list, t_min: int, t_max: int):
    """시각 t 마다 베이 내 co-presence 수. t in [t_min, t_max)."""
    n = [0] * (t_max - t_min)
    for p in placed_list:
        a = max(p["entry"], t_min)
        b = min(p["exit"], t_max)
        for t in range(a, b):
            n[t - t_min] += 1
    return n


def analyze_instance(prob_num: int):
    """단일 인스턴스 진단. 결과 dict 반환."""
    try:
        data, sol = load_instance_and_solution(prob_num)
    except FileNotFoundError as e:
        return {"prob": prob_num, "error": str(e)}

    w = data["weights"]
    w1, w2, w3 = w["w1"], w["w2"], w["w3"]
    m = len(data["bays"])

    # 공식 평가
    r = _utils.check_feasibility(data, sol)
    obj = r.get("objective") or 0
    z1_total = r.get("obj1") or 0
    z2 = r.get("obj2") or 0
    z3 = r.get("obj3") or 0
    feasible = (obj is not None) and (len(r.get("violations", [])) == 0)

    bays_placed = extract_placed(data, sol)

    # 시간 범위
    all_placed = [p for pl in bays_placed.values() for p in pl]
    if not all_placed:
        return {"prob": prob_num, "error": "no placed blocks"}
    t_min = min(p["entry"] for p in all_placed)
    t_max = max(p["exit"] for p in all_placed) + 1

    # 각 베이 co-presence 프로파일
    bay_profiles: dict[int, list] = {}
    for j in range(m):
        pl = bays_placed.get(j, [])
        bay_profiles[j] = copresence_profile(pl, t_min, t_max)

    # 베이별 피크
    bay_peaks: dict[int, dict] = {}
    for j in range(m):
        prof = bay_profiles[j]
        pk = max(prof) if prof else 0
        pk_t = prof.index(pk) + t_min if pk > 0 else t_min
        bay_peaks[j] = {"peak": pk, "peak_t": pk_t}

    # -----------------------------------------------------------------------
    # 크로스베이 기회: 시각 t 에서 어느 베이 혼잡 & 다른 베이 한가
    # t 가 아닌 '기회 유닛(time-steps where opportunity exists)'을 세되,
    # 겹치는 구간을 연속 구간으로 단순히 세서 수치화.
    # -----------------------------------------------------------------------
    T = t_max - t_min
    opp_count = 0          # 기회 유닛 수 (time-steps)
    opp_delta_sum = 0      # Σ (혼잡베이 co-pres - 한가베이 co-pres)  -- 이동 이득 척도

    for t_off in range(T):
        copres = [bay_profiles[j][t_off] for j in range(m)]
        cong_bays = [j for j in range(m) if copres[j] >= CONGESTION_THR]
        slack_bays = [j for j in range(m) if copres[j] <= SLACK_THR]
        if cong_bays and slack_bays:
            opp_count += 1
            best_cong = max(copres[j] for j in cong_bays)
            best_slack = min(copres[j] for j in slack_bays)
            opp_delta_sum += (best_cong - best_slack)

    # -----------------------------------------------------------------------
    # tardy-at-peak 비율
    # tardy 블록이 자기 베이의 피크 시각과 겹치는 비율
    # -----------------------------------------------------------------------
    tardy_blocks = [p for p in all_placed if p["tardiness"] > 0]
    tardy_at_peak = 0
    for p in tardy_blocks:
        j = p["bay"]
        pk_t = bay_peaks[j]["peak_t"]
        if p["entry"] <= pk_t < p["exit"]:
            tardy_at_peak += 1
    tardy_at_peak_ratio = tardy_at_peak / max(1, len(tardy_blocks))

    # -----------------------------------------------------------------------
    # 시간 보완성: 베이 b 가 피크일 때 다른 베이들의 평균 co-presence
    # -----------------------------------------------------------------------
    complementarity: list[str] = []
    for j in range(m):
        pk_t = bay_peaks[j]["peak_t"]
        t_off = pk_t - t_min
        if t_off < 0 or t_off >= T:
            continue
        others_copres = [
            bay_profiles[jj][t_off] for jj in range(m) if jj != j
        ]
        avg_other = sum(others_copres) / max(1, len(others_copres))
        pk = bay_peaks[j]["peak"]
        slack_others = [c for c in others_copres if c <= SLACK_THR]
        has_slack = len(slack_others) > 0
        complementarity.append(
            f"bay{j}: peak={pk}@t{pk_t}, others_avg={avg_other:.1f}, "
            f"has_slack={'YES' if has_slack else 'NO'}"
        )

    # -----------------------------------------------------------------------
    # 트레이드 추정: 선호 외 베이로 옮길 때 z3 비용 vs z1 이득
    # 한 블록을 비선호 베이로 이동시 Δz3 = w3 * (S_max - S_other)
    # z1 감소 추정 = tardiness of that block (낙관치)
    # -----------------------------------------------------------------------
    blocks = data["blocks"]
    n_blocks_total = len(blocks)
    cross_trade_positive = 0  # w1*tardy_gain > w3*z3_cost인 블록 수

    for p in tardy_blocks:
        bid = p["id"]
        j = p["bay"]
        pref = p["pref"]
        if j != pref:
            # 이미 비선호 베이에 있음 — 다른 쪽으로
            continue
        # 다른 베이로 옮기면 z3 페널티: w3 * (best_pref_score - 2nd_best_pref_score)
        prefs = blocks[bid]["bay_preferences"]
        sorted_prefs = sorted(prefs, reverse=True)
        delta_z3 = (sorted_prefs[0] - sorted_prefs[1]) * w3 if len(sorted_prefs) > 1 else 0
        # z1 이득 낙관치 = 그 블록의 현재 tardiness * w1
        gain_z1 = p["tardiness"] * w1
        if gain_z1 > delta_z3:
            cross_trade_positive += 1

    return {
        "prob": prob_num,
        "feasible": feasible,
        "obj": obj,
        "z1": z1_total,
        "z2": z2,
        "z3": z3,
        "w1": w1,
        "w3": w3,
        "w1_w3_ratio": round(w1 / max(1, w3), 1),
        "n_bays": m,
        "n_blocks": n_blocks_total,
        "n_tardy": len(tardy_blocks),
        "tardy_at_peak_ratio": round(tardy_at_peak_ratio, 2),
        "opp_count": opp_count,        # 기회 유닛 수
        "opp_delta_sum": opp_delta_sum, # 기회 강도
        "cross_trade_positive": cross_trade_positive,  # 이동 가치 있는 블록 수
        "bay_peaks": {j: bay_peaks[j] for j in range(m)},
        "complementarity": complementarity,
    }


# -----------------------------------------------------------------------
def main():
    print("=" * 80)
    print("co-presence 크로스베이 이동 잠재력 진단 (set2: prob_21..40)")
    print("해 출처: real_prob_*.json (현재 솔버 실제 해)")
    print("=" * 80)

    results = []
    for prob_num in SET2_RANGE:
        r = analyze_instance(prob_num)
        results.append(r)
        if "error" in r:
            print(f"  prob_{prob_num}: ERROR — {r['error']}")
        else:
            print(f"  prob_{prob_num}: feasible={r['feasible']}, "
                  f"z1={r['z1']:,.0f}, opp={r['opp_count']}ts, "
                  f"cross_trade+={r['cross_trade_positive']}")

    # z1 기준 상위 8개
    valid = [r for r in results if "error" not in r]
    top8 = sorted(valid, key=lambda r: -(r["z1"] or 0))[:8]

    print("\n" + "=" * 80)
    print("[ z1-WORST 상위 8 인스턴스 상세 진단 ]")
    print("=" * 80)

    for r in top8:
        prob = r["prob"]
        print(f"\n--- prob_{prob} ---")
        print(f"  feasible     : {r['feasible']}")
        print(f"  obj          : {r['obj']:,.0f}  "
              f"(z1={r['z1']:,.0f} | z2={r['z2']:,.2f} | z3={r['z3']:,.0f})")
        print(f"  w1={r['w1']:,}  w3={r['w3']}  w1/w3 비율={r['w1_w3_ratio']}")
        print(f"  bays={r['n_bays']}  blocks={r['n_blocks']}  tardy={r['n_tardy']}")
        print(f"  tardy-at-peak 비율 : {r['tardy_at_peak_ratio']:.0%}")
        print(f"  크로스베이 기회 유닛 : {r['opp_count']} timesteps  "
              f"(강도합={r['opp_delta_sum']:,})")
        print(f"  이동 가치 양수 블록 : {r['cross_trade_positive']}")
        print("  베이별 피크:")
        for j, pk in r["bay_peaks"].items():
            print(f"    bay{j}: peak={pk['peak']}  @t={pk['peak_t']}")
        print("  시간 보완성:")
        for line in r["complementarity"]:
            print(f"    {line}")

    # -----------------------------------------------------------------------
    # 한 줄 결론 + 유망 인스턴스
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("[ 요약 테이블 ]")
    print(f"{'prob':>6} {'z1':>12} {'opp_ts':>7} {'opp_δ':>8} "
          f"{'tardy%peak':>10} {'trade+':>7} {'w1/w3':>7}")
    print("-" * 60)
    for r in sorted(valid, key=lambda r: -(r["z1"] or 0)):
        print(f"{r['prob']:>6} {r['z1']:>12,.0f} {r['opp_count']:>7} "
              f"{r['opp_delta_sum']:>8,} {r['tardy_at_peak_ratio']:>9.0%} "
              f"{r['cross_trade_positive']:>7} {r['w1_w3_ratio']:>7.1f}")

    # 유망 인스턴스: opp_count > 0 이고 trade+ > 0 이고 z1이 큰 것
    promising = [
        r for r in valid
        if r["opp_count"] > 50 and r["cross_trade_positive"] > 0
    ]
    promising.sort(key=lambda r: -(r["opp_delta_sum"] * r["cross_trade_positive"]))

    print("\n" + "=" * 80)
    print("[ 결론 ]")
    if promising:
        prob_list = [str(r["prob"]) for r in promising[:3]]
        avg_opp = sum(r["opp_count"] for r in valid) / max(1, len(valid))
        total_with_opp = sum(1 for r in valid if r["opp_count"] > 50)
        print(f"크로스베이 이동 구조 여지: {total_with_opp}/{len(valid)} 인스턴스에서 "
              f"기회 유닛 50ts 이상 (평균 {avg_opp:.0f}ts).")
        print(f"z1 개선 가능성 있는 인스턴스: YES")
        print(f"가장 유망한 인스턴스: prob_{', prob_'.join(prob_list)}")
        print(f"  → 피크 co-presence 시점에 한가한 베이 존재 + w1/w3 비율이 높아")
        print(f"    크로스베이 이동 시 z3 페널티보다 z1 이득이 큼.")
    else:
        total_with_opp = sum(1 for r in valid if r["opp_count"] > 50)
        print(f"기회 유닛 50ts+ 인스턴스: {total_with_opp}/{len(valid)}")
        print("크로스베이 이동으로 z1 줄이기 구조 여지: 제한적.")
        print("대부분 인스턴스에서 피크 시점 다른 베이도 이미 혼잡하거나,")
        print("이동 시 z3 페널티가 z1 이득보다 큼.")

    print("=" * 80)


if __name__ == "__main__":
    main()
