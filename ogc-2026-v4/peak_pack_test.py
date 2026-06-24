"""
peak_pack_test.py -- 정적 피크-패킹 가능성 테스트

질문: z1-worst 베이의 피크 경합집합 S를 동시에(시간 무시)
      CP-SAT exact로 몇 개나 끼울 수 있나?

판정:
  N ≥ |S|            → 공간상 전부 배치 가능 = 패킹 레버 도달가능 (우리 BL이 약함)
  N >> M (현재 동시배치 수)  → 개선 여지 N-M 블록
  N ≈ M              → 폴리곤 모양 벽 (구조적)

대상: prob_38, 40, 27 (set2 z1의 68%)

실행:
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe peak_pack_test.py
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe peak_pack_test.py --probs 38 40 27
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe peak_pack_test.py --timeout 120
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import argparse
from typing import Dict, List, Tuple, Optional

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
V4 = os.path.dirname(os.path.abspath(__file__))
INST_DIR = os.path.normpath(os.path.join(V4, "..", "instances", "train"))

if V4 not in sys.path:
    sys.path.insert(0, V4)

import utils as _utils  # noqa
from utils import Bay, Block, check_collisions  # noqa
from adapter import deserialize  # noqa
from gridmap import build_shape, BlockShape  # noqa

try:
    from ortools.sat.python import cp_model
    HAS_ORTOOLS = True
except ImportError:
    HAS_ORTOOLS = False
    print("[WARN] ortools 없음 — CP-SAT 테스트 불가", flush=True)


# ---------------------------------------------------------------------------
# 인스턴스 + 해 로드
# ---------------------------------------------------------------------------
def load_instance_and_solution(prob_num: int):
    inst_path = os.path.join(INST_DIR, f"prob_{prob_num}.json")
    sol_path = os.path.join(V4, f"real_prob_{prob_num}.json")
    data = json.load(open(inst_path, encoding="utf-8"))
    if not os.path.exists(sol_path):
        raise FileNotFoundError(f"real_prob_{prob_num}.json 없음: {sol_path}")
    sol = json.load(open(sol_path, encoding="utf-8"))
    return data, sol


# ---------------------------------------------------------------------------
# 피크 시점 & 경합 집합 추출
# ---------------------------------------------------------------------------
def find_peak_coexistence(data: dict, sol: dict, bay_id: int):
    """
    특정 베이에서 동시공존 블록 수가 최대인 시점 t* 와 경합집합 S 반환.

    경합집합 S = 이상적 스케줄(R_i에 입고, R_i+P_i에 퇴장)에서 t*에 co-present인 블록들.
    즉 [R_i, R_i+P_i) ∋ t* 이면 S에 포함.

    Returns:
        (t_star, S_ideal, S_actual, M_actual)
        t_star    : 이상적 스케줄에서 동시공존 최대 시점
        S_ideal   : 이상적 스케줄에서 t*에 co-present (경합집합)
        S_actual  : 실제 해에서 t_actual에 가장 많이 co-present인 집합
        M_actual  : 실제 해에서 t*_actual에 동시공존하는 블록 수
    """
    blocks = data["blocks"]
    ops = sol["operations"]

    # 배정 추출: 베이별 블록 목록 + 실제 entry/exit
    entry_info: Dict[int, dict] = {}
    exit_time: Dict[int, int] = {}

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

    # 해당 베이 블록
    bay_bids = [bid for bid, info in entry_info.items()
                if info["bay_id"] == bay_id]

    if not bay_bids:
        return None, [], [], 0

    # 이상적 스케줄 구간: [R_i, R_i + P_i)
    ideal_intervals = []
    for bid in bay_bids:
        R = int(blocks[bid]["release_time"])
        P = int(blocks[bid]["processing_time"])
        ideal_intervals.append((bid, R, R + P))

    # 이상적 피크 시점 탐색 (이벤트 스윕)
    events = []
    for bid, start, end in ideal_intervals:
        events.append((start, +1, bid))
        events.append((end, -1, bid))
    events.sort(key=lambda e: (e[0], e[1]))

    t_star = None
    max_copresent = 0
    S_ideal = []
    cur_set = set()

    for t_ev, typ, bid in events:
        if typ == +1:
            cur_set.add(bid)
        else:
            cur_set.discard(bid)
        cnt = len(cur_set)
        if cnt > max_copresent:
            max_copresent = cnt
            t_star = t_ev
            S_ideal = list(cur_set)

    # 실제 해에서 최대 공존 시점 탐색
    actual_intervals = []
    for bid in bay_bids:
        actual_entry = entry_info[bid]["entry"]
        actual_exit = exit_time.get(bid, actual_entry + blocks[bid]["processing_time"])
        actual_intervals.append((bid, actual_entry, actual_exit))

    events2 = []
    for bid, start, end in actual_intervals:
        events2.append((start, +1, bid))
        events2.append((end, -1, bid))
    events2.sort(key=lambda e: (e[0], e[1]))

    max_actual = 0
    S_actual = []
    cur_set2 = set()
    for t_ev, typ, bid in events2:
        if typ == +1:
            cur_set2.add(bid)
        else:
            cur_set2.discard(bid)
        cnt = len(cur_set2)
        if cnt > max_actual:
            max_actual = cnt
            S_actual = list(cur_set2)

    return t_star, S_ideal, S_actual, max_actual


# ---------------------------------------------------------------------------
# 최악의 베이 찾기 (z1 기준)
# ---------------------------------------------------------------------------
def find_worst_bay(data: dict, sol: dict) -> Tuple[int, float]:
    """z1(tardiness)이 가장 큰 베이 반환."""
    blocks = data["blocks"]
    ops = sol["operations"]

    entry_info: Dict[int, dict] = {}
    exit_time: Dict[int, int] = {}

    for t_str, op_list in ops.items():
        t = int(t_str)
        for op in op_list:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                entry_info[bid] = {"bay_id": int(op["bay_id"]), "entry": t}
            elif op["type"] == "EXIT":
                exit_time[bid] = t

    bay_z1: Dict[int, float] = {}
    for bid, info in entry_info.items():
        j = info["bay_id"]
        exit_t = exit_time.get(bid, info["entry"] + blocks[bid]["processing_time"])
        due = int(blocks[bid]["due_date"])
        tard = max(0, exit_t - due)
        bay_z1[j] = bay_z1.get(j, 0.0) + tard

    if not bay_z1:
        return 0, 0.0
    worst_bay = max(bay_z1, key=lambda j: bay_z1[j])
    return worst_bay, bay_z1[worst_bay]


# ---------------------------------------------------------------------------
# 정적 패킹 CP-SAT (시간 무시, 공간만)
# ---------------------------------------------------------------------------
def static_packing_cpsat(
    data: dict,
    bay_id: int,
    block_ids: List[int],
    timeout_s: float = 120.0,
    with_crane: bool = False,
    coarse_n_x: int = 8,
    coarse_n_y: int = 4,
) -> Tuple[int, str, float]:
    """
    경합집합의 블록들을 베이 안에 동시에(시간 무시) 겹침 없이 최대 몇 개 배치 가능한가.

    Args:
        data        : 인스턴스 dict
        bay_id      : 대상 베이
        block_ids   : 경합 블록 id 목록
        timeout_s   : CP-SAT 시간 제한
        with_crane  : True → 크레인 j≥k 제약도 추가 (실제 물리 제약 전부)
        coarse_n_x  : x 방향 이산 후보 수 (블록 크기에 따라 조정)
        coarse_n_y  : y 방향 이산 후보 수

    Returns:
        (N, status_str, wall_s)
        N = 동시배치 가능한 최대 블록 수
    """
    if not HAS_ORTOOLS or not block_ids:
        return 0, "NO_ORTOOLS", 0.0

    n = len(block_ids)
    bay_data = data["bays"][bay_id]
    W = int(bay_data["width"])
    H = int(bay_data["height"])
    bay = Bay.from_dict(bay_data, bay_id)

    # 블록별 위치 후보 생성 (이산 후보 집합)
    # 각 블록은 모든 방향 × coarse x후보 × coarse y후보 로 후보 생성
    # 총 후보 수가 너무 크면 더 줄임
    all_candidates = {}  # bid -> list of (x, y, orient_idx, BlockShape)
    blocks_data = data["blocks"]

    for bid in block_ids:
        blk_data = blocks_data[bid]
        n_orients = len(blk_data["shape"])
        cands = []

        for o in range(n_orients):
            sh = build_shape(bid, blk_data, o, scale=2)

            # x 범위 계산
            x_lb = max(0, int(math.ceil(-sh.min_x - 1e-9)))
            x_ub = max(x_lb, int(math.floor(W - sh.max_x + 1e-9)))
            # y 범위 계산
            y_lb = max(0, int(math.ceil(-sh.min_y - 1e-9)))
            y_ub = max(y_lb, int(math.floor(H - sh.max_y + 1e-9)))

            # x 이산 후보
            if x_ub <= x_lb:
                x_vals = [x_lb]
            else:
                step_x = max(1, (x_ub - x_lb) // max(1, coarse_n_x - 1))
                x_vals = list(range(x_lb, x_ub + 1, step_x))
                if x_ub not in x_vals:
                    x_vals.append(x_ub)

            # y 이산 후보
            if y_ub <= y_lb:
                y_vals = [y_lb]
            else:
                step_y = max(1, (y_ub - y_lb) // max(1, coarse_n_y - 1))
                y_vals = list(range(y_lb, y_ub + 1, step_y))
                if y_ub not in y_vals:
                    y_vals.append(y_ub)

            for xv in x_vals:
                for yv in y_vals:
                    cands.append((xv, yv, o, sh))

        all_candidates[bid] = cands

    # 후보 수 합계 출력
    total_cands = sum(len(c) for c in all_candidates.values())
    max_cands = max(len(c) for c in all_candidates.values())
    print(f"    candidates: total={total_cands}, max_per_block={max_cands}", flush=True)

    # 후보 수가 너무 크면 줄임 (combo 폭발 방지)
    MAX_CANDS_PER_BLOCK = 40
    if max_cands > MAX_CANDS_PER_BLOCK:
        print(f"    [trim] {max_cands} -> {MAX_CANDS_PER_BLOCK} per block", flush=True)
        for bid in block_ids:
            cands = all_candidates[bid]
            if len(cands) > MAX_CANDS_PER_BLOCK:
                # 고르게 샘플링
                step = len(cands) / MAX_CANDS_PER_BLOCK
                all_candidates[bid] = [cands[int(i * step)] for i in range(MAX_CANDS_PER_BLOCK)]

    # 충돌 쌍 사전계산 (후보 콤보별)
    t_precompute = time.monotonic()

    # pair_overlap[(a, b, ci_a, ci_b)] = True if collision
    pair_overlap: Dict[Tuple, bool] = {}
    # crane pair: (a, b, ci_a, ci_b) → (ba_e, ab_e, ba_x, ab_x) for with_crane
    pair_crane: Dict[Tuple, Tuple] = {}

    # Block 객체 캐시
    blk_cache: Dict[Tuple, Block] = {}

    def get_blk(bid, pose_idx):
        key = (bid, pose_idx)
        if key not in blk_cache:
            x, y, o, sh = all_candidates[bid][pose_idx]
            blk_cache[key] = Block(block_id=bid, block_data=blocks_data[bid],
                                   x=x, y=y, orient_idx=o)
        return blk_cache[key]

    for ia, a in enumerate(block_ids):
        for ib, b in enumerate(block_ids):
            if ib <= ia:
                continue
            ca_list = all_candidates[a]
            cb_list = all_candidates[b]
            for ci_a in range(len(ca_list)):
                blk_a = get_blk(a, ci_a)
                for ci_b in range(len(cb_list)):
                    blk_b = get_blk(b, ci_b)
                    coll = bool(check_collisions(bay, [blk_a, blk_b]))
                    pair_overlap[(a, b, ci_a, ci_b)] = coll
                    if with_crane and not coll:
                        from utils import check_entry as ce, check_exit as cx
                        ba_e = bool(ce(bay, [blk_b], blk_a, fast=True))
                        ab_e = bool(ce(bay, [blk_a], blk_b, fast=True))
                        ba_x = bool(cx(bay, [blk_b], blk_a, fast=True))
                        ab_x = bool(cx(bay, [blk_a], blk_b, fast=True))
                        if ba_e or ab_e or ba_x or ab_x:
                            pair_crane[(a, b, ci_a, ci_b)] = (ba_e, ab_e, ba_x, ab_x)

    precompute_wall = time.monotonic() - t_precompute
    print(f"    precompute: {precompute_wall:.1f}s  "
          f"stored_collisions={sum(1 for v in pair_overlap.values() if v)}", flush=True)

    # CP-SAT 모델 구축
    model = cp_model.CpModel()

    # 결정변수
    # sel[bid][ci] = 1 if 블록 bid가 후보 ci에 배치됨
    # placed[bid]  = 1 if 블록 bid가 어딘가에 배치됨 (선택됨)
    sel = {}
    placed_var = {}
    for bid in block_ids:
        nb = len(all_candidates[bid])
        sel[bid] = [model.NewBoolVar(f"sel_{bid}_{ci}") for ci in range(nb)]
        placed_var[bid] = model.NewBoolVar(f"placed_{bid}")

        # placed → exactly one candidate chosen; not placed → all sel = 0
        # placed[bid] = sum(sel[bid])
        model.Add(sum(sel[bid]) == placed_var[bid])

    # 충돌 금지: 두 블록이 같은 후보 콤보에 둘 다 배치되면 금지
    for ia, a in enumerate(block_ids):
        for ib, b in enumerate(block_ids):
            if ib <= ia:
                continue
            ca_list = all_candidates[a]
            cb_list = all_candidates[b]
            for ci_a in range(len(ca_list)):
                for ci_b in range(len(cb_list)):
                    if pair_overlap.get((a, b, ci_a, ci_b), False):
                        # sel_a[ci_a] AND sel_b[ci_b] 불가
                        model.AddBoolOr([sel[a][ci_a].Not(), sel[b][ci_b].Not()])

                    # 크레인 제약 (정적 공간 해석)
                    # 크레인 제약은 시간 의존적이라 정적 패킹에선 위치만으로 판단 어려움
                    # → with_crane=True일 때만 추가 (j≥k 직접 적용은 항상 시간의존, 여기선 생략)
                    # 실제 크레인 제약은 시간에 의존하므로 정적 테스트에서 공간만 테스트

    # 목적: 최대 블록 수 배치
    model.Maximize(sum(placed_var[bid] for bid in block_ids))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(timeout_s)
    solver.parameters.num_search_workers = 4

    t0 = time.monotonic()
    status_code = solver.Solve(model)
    wall = time.monotonic() - t0

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status_str = status_map.get(status_code, f"STATUS_{status_code}")

    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        N = int(round(solver.ObjectiveValue()))
    else:
        N = 0

    return N, status_str, wall


# ---------------------------------------------------------------------------
# 면적 기준 공간 점유율 계산
# ---------------------------------------------------------------------------
def compute_area_stats(data: dict, bay_id: int, block_ids: List[int]) -> dict:
    """경합집합의 면적 합 vs 베이 면적."""
    bay_data = data["bays"][bay_id]
    W = int(bay_data["width"])
    H = int(bay_data["height"])
    bay_area = W * H  # (실수 스케일)

    blocks_data = data["blocks"]
    total_block_area = 0.0
    for bid in block_ids:
        blk_data = blocks_data[bid]
        # orientation 0 기준 면적 (방향 무관하게 동일)
        sh = build_shape(bid, blk_data, 0, scale=2)
        # scale=2이므로 실제 면적은 /4
        total_block_area += sh.footprint_area / 4.0

    bay_area_actual = W * H
    pct = (total_block_area / bay_area_actual * 100.0) if bay_area_actual > 0 else 0.0

    return {
        "bay_area": bay_area_actual,
        "total_block_area": total_block_area,
        "area_pct": pct,
    }


# ---------------------------------------------------------------------------
# 단일 인스턴스 테스트
# ---------------------------------------------------------------------------
def test_instance(prob_num: int, timeout_s: float = 120.0) -> dict:
    t_total = time.monotonic()

    try:
        data, sol = load_instance_and_solution(prob_num)
    except FileNotFoundError as e:
        return {"prob": prob_num, "error": str(e)}

    # 공식 z1 확인
    try:
        r = _utils.check_feasibility(data, sol)
        full_z1 = float(r.get("obj1") or 0)
        feasible = (r.get("objective") is not None) and (len(r.get("violations", [])) == 0)
    except Exception as e:
        return {"prob": prob_num, "error": f"check_feasibility 실패: {e}"}

    if not feasible:
        return {"prob": prob_num, "error": "infeasible solution"}

    # 최악의 베이 찾기
    worst_bay, bay_z1 = find_worst_bay(data, sol)
    print(f"  worst bay = {worst_bay}, bay_z1 = {bay_z1:.0f}", flush=True)

    # 경합집합 추출
    t_star, S_ideal, S_actual, M_actual = find_peak_coexistence(data, sol, worst_bay)
    print(f"  t_star={t_star}, |S_ideal|={len(S_ideal)}, "
          f"|S_actual|={len(S_actual)}, M_actual={M_actual}", flush=True)

    if not S_ideal:
        return {"prob": prob_num, "error": "경합집합 추출 실패"}

    # 면적 통계
    area_stats = compute_area_stats(data, worst_bay, S_ideal)
    print(f"  S_ideal 면적: {area_stats['total_block_area']:.1f} / "
          f"{area_stats['bay_area']} = {area_stats['area_pct']:.1f}%", flush=True)

    # CP-SAT 정적 패킹 (공간만)
    print(f"  [공간only] CP-SAT 정적 패킹 timeout={timeout_s}s ...", flush=True)
    t0 = time.monotonic()
    N_space, status_space, wall_space = static_packing_cpsat(
        data, worst_bay, S_ideal,
        timeout_s=timeout_s,
        with_crane=False,
    )
    print(f"  [공간only] N={N_space}, status={status_space}, "
          f"wall={wall_space:.1f}s", flush=True)

    # 판정
    S_sz = len(S_ideal)
    M = M_actual

    wall_total = time.monotonic() - t_total

    result = {
        "prob": prob_num,
        "full_z1": full_z1,
        "worst_bay": worst_bay,
        "bay_z1": bay_z1,
        "t_star": t_star,
        "S_size": S_sz,          # 경합집합 크기
        "area_pct": area_stats["area_pct"],  # 경합집합 면적 / 베이 면적
        "M_actual": M,            # 우리 해의 최대 동시배치 수
        "N_space": N_space,       # 공간only CP-SAT 최대 배치 수
        "status_space": status_space,
        "gap_space": N_space - M, # 공간 개선 여지
        "feasibility_ratio": N_space / S_sz if S_sz > 0 else 0.0,
        "wall_s": round(wall_total, 1),
    }

    return result


# ---------------------------------------------------------------------------
# 결과 출력 + 판정
# ---------------------------------------------------------------------------
def print_results(results: list):
    valid = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    print()
    print("=" * 110)
    print("[ 정적 피크-패킹 가능성 테스트 ]")
    print("  질문: 경합집합 S를 동시에 (시간 무시, 공간만) 몇 개나 배치 가능한가?")
    print("=" * 110)

    hdr = (
        f"{'prob':>6} | {'full_z1':>9} {'bay':>4} {'bay_z1':>8} | "
        f"{'|S|':>5} {'area%':>6} | {'M_now':>6} {'N_space':>8} {'gap':>6} {'feas%':>6} | "
        f"{'status':>10} {'wall':>5}"
    )
    print(hdr)
    print("-" * 110)

    for r in valid:
        feas_pct = r["feasibility_ratio"] * 100.0
        row = (
            f"{r['prob']:>6} | "
            f"{r['full_z1']:>9,.0f} "
            f"{r['worst_bay']:>4} "
            f"{r['bay_z1']:>8,.0f} | "
            f"{r['S_size']:>5} "
            f"{r['area_pct']:>5.1f}% | "
            f"{r['M_actual']:>6} "
            f"{r['N_space']:>8} "
            f"{r['gap_space']:>+6} "
            f"{feas_pct:>5.1f}% | "
            f"{r['status_space']:>10} "
            f"{r['wall_s']:>4.0f}s"
        )
        print(row)

    if errors:
        print()
        print("[ 에러 ]")
        for r in errors:
            print(f"  prob_{r['prob']}: {r['error']}")

    print()
    print("=" * 110)
    print("[ 핵심 판정 ]")
    print()

    for r in valid:
        S_sz = r["S_size"]
        M = r["M_actual"]
        N = r["N_space"]
        gap = r["gap_space"]

        print(f"  prob_{r['prob']} (worst bay={r['worst_bay']}):")
        print(f"    경합집합 |S| = {S_sz}  (면적 {r['area_pct']:.1f}% of 베이)")
        print(f"    현재 해 최대 동시배치 M = {M}")
        print(f"    공간only CP-SAT 최대 배치 N = {N}  [{r['status_space']}]")
        print(f"    개선 여지 (N - M) = {gap:+d}")

        if N >= S_sz:
            print(f"    --> 판정: S 전부({S_sz}개) 동시배치 가능 (공간 OK)")
            print(f"           = 패킹 레버 도달가능. 우리 BL이 약해서 못 끼운 것.")
            if gap > 0:
                print(f"           = z1 프라이즈 실재: N-M={gap}개 블록 동시화 여지")
        elif N > M:
            print(f"    --> 판정: 일부 개선 가능 (N={N} > M={M})")
            print(f"           = 패킹 레버 부분적으로 도달가능 (N-M={gap}개)")
            print(f"           = S를 전부 동시배치하긴 어렵지만 일부 개선 가능")
        elif N == M:
            print(f"    --> 판정: 개선 여지 없음 (N=M={M})")
            print(f"           = 현재 해가 이미 공간상 최적에 가까움")
            print(f"           = 폴리곤 모양 벽이거나 현재 배치가 이미 최적")
        else:
            print(f"    --> 판정: N={N} < M={M} (CP-SAT 타임아웃/탐색 미완)")
            print(f"           = 더 긴 타임아웃 필요 또는 후보 수 확대 필요")
        print()

    # 종합 판정
    if valid:
        total_gap = sum(r["gap_space"] for r in valid)
        lever_probs = [r["prob"] for r in valid if r["N_space"] >= r["S_size"]]
        partial_probs = [r["prob"] for r in valid
                         if r["gap_space"] > 0 and r["N_space"] < r["S_size"]]

        print("  [ 종합 결론 ]")
        print(f"  total gap (N-M) across tested probs = {total_gap:+d}")
        if lever_probs:
            print(f"  패킹 레버 도달가능 인스턴스: {lever_probs}")
            print("  --> z1 개선은 더 조밀한 초기 레이아웃(BL/CP-SAT 패킹)으로 가능")
            print("  --> 경쟁자 우위는 패킹 알고리즘 차이일 가능성 높음")
        elif partial_probs:
            print(f"  부분 개선 가능 인스턴스: {partial_probs}")
            print("  --> 패킹 레버 일부 작동하나 전체 경합집합 수용은 불가")
        else:
            print("  --> 전 인스턴스에서 패킹 개선 여지 없음")
            print("  --> z1은 폴리곤 모양 구조적 벽 (크레인 직렬화 불가피)")
            print("  --> z3 최적화로 피벗 권고")

    print("=" * 110)


# ---------------------------------------------------------------------------
# JSON 저장
# ---------------------------------------------------------------------------
def save_results(results: list, path: str):
    def _serial(r):
        return {k: (v if not isinstance(v, float) or math.isfinite(v) else None)
                for k, v in r.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump([_serial(r) for r in results], f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {path}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
DEFAULT_TARGETS = [38, 40, 27]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="정적 피크-패킹 가능성 테스트")
    parser.add_argument("--probs", nargs="+", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="인스턴스당 CP-SAT 타임아웃(초, 기본 120)")
    args = parser.parse_args()

    target = args.probs if args.probs is not None else DEFAULT_TARGETS

    print(f"[peak_pack_test] 대상: {target}", flush=True)
    print(f"[peak_pack_test] CP-SAT timeout: {args.timeout}s", flush=True)
    print(f"[peak_pack_test] ortools: {HAS_ORTOOLS}", flush=True)
    print()

    results = []
    for prob_num in target:
        print(f"\n{'='*50}", flush=True)
        print(f"  prob_{prob_num}", flush=True)
        print(f"{'='*50}", flush=True)
        try:
            r = test_instance(prob_num, timeout_s=args.timeout)
        except Exception as e:
            import traceback
            lines = traceback.format_exc().splitlines()
            short = "\n".join(lines[-5:])
            print(f"  EXCEPTION:\n{short}", flush=True)
            r = {"prob": prob_num, "error": str(e)}
        results.append(r)

    print_results(results)

    out_path = os.path.join(V4, "peak_pack_results.json")
    save_results(results, out_path)
