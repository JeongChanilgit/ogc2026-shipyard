"""
z1_decomp.py -- z1(tardiness) 3-단계 분해 측정

고정 레이아웃 위에서 단조 관계 분해:
    intrinsic LB ≤ space-only z1 ≤ full z1

정의:
  intrinsic LB   : Σ max(0, R_i + P_i - due_i)  (공간/크레인 무관, 산술)
  space-only z1  : 고정 레이아웃, 풋프린트 겹치는 쌍만 disjunction (크레인 j≥k 무시)
  full z1        : 실제 해의 z1 (공식 utils 체커)
  crane z1       : full - space-only
  space z1       : space-only - intrinsic
  inevitable     : intrinsic

실행:
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe z1_decomp.py
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe z1_decomp.py --probs 38 40 27 33
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe z1_decomp.py --timeout 60
"""
from __future__ import annotations

import json
import os
import sys
import time
import argparse
from typing import Dict, List, Tuple, Optional

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
V4 = os.path.dirname(os.path.abspath(__file__))
V3 = os.path.normpath(os.path.join(V4, "..", "ogc-2026-v3"))
INST_DIR = os.path.normpath(os.path.join(V4, "..", "instances", "train"))

for d in [V4, V3]:
    if d not in sys.path:
        sys.path.insert(0, d)

import utils as _utils  # noqa

# adapter & seed (v4 우선, v3 fallback)
try:
    from adapter import deserialize
except ImportError:
    from adapter import deserialize  # type: ignore

try:
    from seed import global_eval
except ImportError:
    from seed import global_eval  # type: ignore

# ---------------------------------------------------------------------------
# OR-Tools CP-SAT (space-only 최적화)
# ---------------------------------------------------------------------------
try:
    from ortools.sat.python import cp_model
    HAS_ORTOOLS = True
except ImportError:
    HAS_ORTOOLS = False
    print("[WARN] ortools 없음 — space-only z1 를 구간 겹침 스케줄(휴리스틱)로 추정", flush=True)


# ---------------------------------------------------------------------------
# 인스턴스 + 해 로드
# ---------------------------------------------------------------------------
def load_instance_and_solution(prob_num: int):
    inst_path = os.path.join(INST_DIR, f"prob_{prob_num}.json")
    sol_path = os.path.join(V4, f"real_prob_{prob_num}.json")

    data = json.load(open(inst_path, encoding="utf-8"))

    if not os.path.exists(sol_path):
        raise FileNotFoundError(f"real_prob_{prob_num}.json 없음 (v4 경로): {sol_path}")

    sol = json.load(open(sol_path, encoding="utf-8"))
    return data, sol


# ---------------------------------------------------------------------------
# 풋프린트 겹침 판정 (Shapely layer-0 polygon)
# ---------------------------------------------------------------------------
def _footprints_overlap(pa: dict, pb: dict) -> bool:
    """두 placed 레코드의 바닥 풋프린트(layer 0 polygon)가 겹치는지."""
    world_a = pa.get("world")
    world_b = pb.get("world")
    if world_a is None or world_b is None:
        return False
    poly_a = world_a.get(0)
    poly_b = world_b.get(0)
    if poly_a is None or poly_b is None:
        return False
    try:
        return poly_a.intersects(poly_b)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 1단계: intrinsic LB (산술, CP-SAT 불필요)
# ---------------------------------------------------------------------------
def compute_intrinsic(data: dict, bay_placed: Dict[int, list]) -> float:
    """각 블록이 release에 입고, release+P에 퇴장. 공간/크레인 무시."""
    blocks = data["blocks"]
    total = 0.0
    for j, placed_list in bay_placed.items():
        for p in placed_list:
            bid = p["id"]
            R = int(blocks[bid]["release_time"])
            P = int(blocks[bid]["processing_time"])
            due = int(blocks[bid]["due_date"])
            exit_earliest = R + P
            total += max(0, exit_earliest - due)
    return total


# ---------------------------------------------------------------------------
# 2단계: space-only z1 (CP-SAT per bay)
# ---------------------------------------------------------------------------
def _space_only_bay_cpsat(
    data: dict,
    j: int,
    placed_list: list,
    timeout_s: float = 60.0,
) -> Tuple[float, str]:
    """
    고정 레이아웃에서 풋프린트가 겹치는 쌍만 disjunction (크레인 j>=k 무시).
    entry_i >= R_i, exit_i = entry_i + P_i, minimize Σ max(0, exit_i - due_i).

    Returns (space_only_z1_for_bay, status_str)
    """
    if not placed_list:
        return 0.0, "EMPTY"

    blocks = data["blocks"]
    n = len(placed_list)

    # 블록 파라미터
    ids = [p["id"] for p in placed_list]
    R = [int(blocks[bid]["release_time"]) for bid in ids]
    P = [int(blocks[bid]["processing_time"]) for bid in ids]
    due = [int(blocks[bid]["due_date"]) for bid in ids]

    # 시간 상한: 넉넉하게 최대 release + 최대 processing * n
    t_max = max(R[i] + P[i] for i in range(n)) + sum(P) + 1

    # 풋프린트 겹치는 쌍 목록 (고정 레이아웃 기준)
    overlap_pairs: List[Tuple[int, int]] = []
    for a in range(n):
        for b in range(a + 1, n):
            if _footprints_overlap(placed_list[a], placed_list[b]):
                overlap_pairs.append((a, b))

    if not HAS_ORTOOLS:
        # 휴리스틱 폴백: EDD 순 직렬화 (겹치는 쌍만)
        return _space_only_heuristic(ids, R, P, due, overlap_pairs), "HEURISTIC"

    model = cp_model.CpModel()

    # 결정변수: entry_i (정수)
    entry_vars = [model.NewIntVar(R[i], t_max, f"e{i}") for i in range(n)]

    # exit_i = entry_i + P_i
    exit_vars = [model.NewIntVar(R[i] + P[i], t_max + max(P), f"x{i}") for i in range(n)]
    for i in range(n):
        model.Add(exit_vars[i] == entry_vars[i] + P[i])

    # disjunction: 겹치는 쌍 (a,b) => exit_a <= entry_b OR exit_b <= entry_a
    for a, b in overlap_pairs:
        b_ab = model.NewBoolVar(f"d{a}_{b}")
        model.Add(exit_vars[a] <= entry_vars[b]).OnlyEnforceIf(b_ab)
        model.Add(exit_vars[b] <= entry_vars[a]).OnlyEnforceIf(b_ab.Not())

    # tardiness vars: tard_i = max(0, exit_i - due_i)
    tard_vars = []
    for i in range(n):
        tard = model.NewIntVar(0, t_max, f"t{i}")
        model.AddMaxEquality(tard, [exit_vars[i] - due[i], model.NewConstant(0)])
        tard_vars.append(tard)

    model.Minimize(sum(tard_vars))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_s
    solver.parameters.num_workers = 4
    status = solver.Solve(model)

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status_str = status_map.get(status, str(status))

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return float(solver.ObjectiveValue()), status_str
    else:
        # 폴백: 휴리스틱
        h = _space_only_heuristic(ids, R, P, due, overlap_pairs)
        return h, f"{status_str}→HEURISTIC"


def _space_only_heuristic(
    ids: list, R: list, P: list, due: list,
    overlap_pairs: List[Tuple[int, int]],
) -> float:
    """
    EDD-스케줄 폴백 (겹치는 쌍만 직렬화). Upper bound.
    겹침 그래프의 연결 컴포넌트별로 EDD 직렬화.
    """
    n = len(ids)
    if n == 0:
        return 0.0

    # 겹침 그래프 인접리스트
    adj: Dict[int, set] = {i: set() for i in range(n)}
    for a, b in overlap_pairs:
        adj[a].add(b)
        adj[b].add(a)

    # BFS 컴포넌트
    visited = [False] * n
    total_tard = 0.0

    for start in range(n):
        if visited[start]:
            continue
        # BFS
        comp = []
        q = [start]
        visited[start] = True
        while q:
            cur = q.pop()
            comp.append(cur)
            for nb in adj[cur]:
                if not visited[nb]:
                    visited[nb] = True
                    q.append(nb)

        if len(comp) == 1:
            i = comp[0]
            exit_t = R[i] + P[i]
            total_tard += max(0, exit_t - due[i])
        else:
            # EDD 순 직렬화
            comp.sort(key=lambda i: due[i])
            cur_t = 0
            for i in comp:
                start_t = max(R[i], cur_t)
                exit_t = start_t + P[i]
                total_tard += max(0, exit_t - due[i])
                cur_t = exit_t

    return total_tard


def compute_space_only(
    data: dict,
    bay_placed: Dict[int, list],
    timeout_per_bay: float = 60.0,
) -> Tuple[float, Dict[int, str]]:
    """전체 인스턴스의 space-only z1 계산 (베이별 합산)."""
    total = 0.0
    bay_status: Dict[int, str] = {}
    for j, placed_list in bay_placed.items():
        val, st = _space_only_bay_cpsat(data, j, placed_list, timeout_per_bay)
        total += val
        bay_status[j] = st
    return total, bay_status


# ---------------------------------------------------------------------------
# 3단계: full z1 (공식 체커)
# ---------------------------------------------------------------------------
def compute_full_z1(data: dict, sol: dict) -> Tuple[float, bool]:
    """공식 check_feasibility 로 full z1 + feasibility 반환."""
    r = _utils.check_feasibility(data, sol)
    feasible = (r.get("objective") is not None) and (len(r.get("violations", [])) == 0)
    z1 = float(r.get("obj1") or 0)
    return z1, feasible


# ---------------------------------------------------------------------------
# 단일 인스턴스 분해
# ---------------------------------------------------------------------------
def decompose_instance(prob_num: int, timeout_per_bay: float = 60.0) -> dict:
    t0 = time.monotonic()

    try:
        data, sol = load_instance_and_solution(prob_num)
    except FileNotFoundError as e:
        return {"prob": prob_num, "error": str(e)}

    blocks = data["blocks"]
    weights = data["weights"]
    w1 = weights["w1"]
    n_bays = len(data["bays"])
    n_blocks = len(blocks)

    # 공식 full z1
    try:
        full_z1, feasible = compute_full_z1(data, sol)
    except Exception as e:
        return {"prob": prob_num, "error": f"full_z1 실패: {e}"}

    # placed 레코드 복원 (Shapely 폴리곤 포함)
    try:
        bay_placed = deserialize(data, sol, scale=2)
    except Exception as e:
        return {"prob": prob_num, "error": f"deserialize 실패: {e}"}

    # intrinsic LB (산술)
    intrinsic = compute_intrinsic(data, bay_placed)

    # space-only z1 (CP-SAT, per bay)
    space_only, bay_status = compute_space_only(data, bay_placed, timeout_per_bay)

    wall = time.monotonic() - t0

    # 분해 값
    crane_z1 = max(0.0, full_z1 - space_only)
    space_z1 = max(0.0, space_only - intrinsic)
    inev_z1 = intrinsic

    # 비율 (full z1 기준)
    denom = full_z1 if full_z1 > 0 else 1.0
    crane_pct = crane_z1 / denom * 100
    space_pct = space_z1 / denom * 100
    inev_pct = inev_z1 / denom * 100

    # 총 tardiness 블록 수
    total_tardy_blocks = sum(
        1 for pl in bay_placed.values()
        for p in pl
        if max(0, p["exit"] - blocks[p["id"]]["due_date"]) > 0
    )

    return {
        "prob": prob_num,
        "feasible": feasible,
        "n_bays": n_bays,
        "n_blocks": n_blocks,
        "n_tardy_blocks": total_tardy_blocks,
        "w1": w1,
        "full_z1": full_z1,
        "space_only_z1": space_only,
        "intrinsic_z1": intrinsic,
        "crane_z1": crane_z1,
        "space_z1": space_z1,
        "crane_pct": crane_pct,
        "space_pct": space_pct,
        "inev_pct": inev_pct,
        "bay_cpsat_status": bay_status,
        "wall_s": round(wall, 1),
    }


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def print_table(results: list):
    valid = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    print()
    print("=" * 120)
    print("[ z1 3단계 분해: intrinsic LB / space-only / full ]")
    print("=" * 120)
    hdr = (
        f"{'prob':>6} | {'full_z1':>10} {'space_z1':>10} {'intrin':>8} | "
        f"{'crane_z1':>10} {'crane%':>7} | {'space_z1_net':>12} {'space%':>7} | "
        f"{'inev_z1':>8} {'inev%':>6} | {'tardy_blk':>9} {'w1':>8} | "
        f"{'wall':>5}"
    )
    print(hdr)
    print("-" * 120)

    for r in valid:
        row = (
            f"{r['prob']:>6} | "
            f"{r['full_z1']:>10,.0f} "
            f"{r['space_only_z1']:>10,.0f} "
            f"{r['intrinsic_z1']:>8,.0f} | "
            f"{r['crane_z1']:>10,.0f} "
            f"{r['crane_pct']:>6.1f}% | "
            f"{r['space_z1']:>12,.0f} "
            f"{r['space_pct']:>6.1f}% | "
            f"{r['intrinsic_z1']:>8,.0f} "
            f"{r['inev_pct']:>5.1f}% | "
            f"{r['n_tardy_blocks']:>9} "
            f"{r['w1']:>8,} | "
            f"{r['wall_s']:>4.0f}s"
        )
        print(row)

    if errors:
        print()
        print("[ 에러 ]")
        for r in errors:
            print(f"  prob_{r['prob']}: {r['error']}")

    # 합계 (set2 + set1 분리)
    set2 = [r for r in valid if r["prob"] >= 21]
    set1 = [r for r in valid if r["prob"] <= 20]

    print()
    print("=" * 120)
    print("[ 합계 ]")

    for label, subset in [("set2 (prob_21..40)", set2), ("set1 (prob_1..20)", set1),
                          ("전체", valid)]:
        if not subset:
            continue
        s_full = sum(r["full_z1"] for r in subset)
        s_space = sum(r["space_only_z1"] for r in subset)
        s_intr = sum(r["intrinsic_z1"] for r in subset)
        s_crane = sum(r["crane_z1"] for r in subset)
        s_spnet = sum(r["space_z1"] for r in subset)
        s_inev = sum(r["intrinsic_z1"] for r in subset)
        d = s_full if s_full > 0 else 1.0
        print(f"  {label}: full_z1={s_full:,.0f} | "
              f"crane={s_crane:,.0f}({s_crane/d*100:.1f}%) "
              f"space={s_spnet:,.0f}({s_spnet/d*100:.1f}%) "
              f"inev={s_inev:,.0f}({s_inev/d*100:.1f}%)")

    print()
    print("=" * 120)
    print("[ 핵심 결론 ]")
    if set2:
        s_full = sum(r["full_z1"] for r in set2)
        s_crane = sum(r["crane_z1"] for r in set2)
        s_spnet = sum(r["space_z1"] for r in set2)
        s_inev = sum(r["intrinsic_z1"] for r in set2)
        d = s_full if s_full > 0 else 1.0

        print(f"  set2 z1 합계 = {s_full:,.0f}")
        print(f"    크레인-유발  : {s_crane:,.0f} ({s_crane/d*100:.1f}%)  ← 크레인-인지 레이아웃 레버")
        print(f"    공간-유발    : {s_spnet:,.0f} ({s_spnet/d*100:.1f}%)  ← 배정/패킹 레버")
        print(f"    불가피(LB)   : {s_inev:,.0f} ({s_inev/d*100:.1f}%)  ← 아무것도 못함")
        print()

        if s_crane / d > 0.4:
            print("  판정: 크레인-유발 z1 비중 > 40%")
            print("    → 크레인-인지 레이아웃(j≥k 고려한 재배치) 레버 살아있음.")
            # 인스턴스별 유망도
            top_crane = sorted(set2, key=lambda r: -r["crane_z1"])[:5]
            print("    가장 유망한 인스턴스 (crane_z1 절대값 순):")
            for r in top_crane:
                print(f"      prob_{r['prob']}: crane_z1={r['crane_z1']:,.0f} ({r['crane_pct']:.1f}%)")
        elif s_spnet / d > 0.4:
            print("  판정: 공간-유발 z1 비중 > 40%")
            print("    → 패킹 밀도/배정 레버. 크레인-인지 레이아웃만으로는 부족.")
        else:
            print("  판정: 불가피 z1(LB)이 지배적.")
            print("    → z1 레버 고갈. z3 최적화로 피벗 권고.")

    print("=" * 120)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
DEFAULT_SET2 = [38, 40, 27, 33, 37, 39, 32, 26]
DEFAULT_SET1 = [14, 20, 13, 12]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="z1 3단계 분해 측정")
    parser.add_argument(
        "--probs", nargs="+", type=int,
        default=None,
        help=f"대상 인스턴스 번호 (기본: set2 worst 8 + set1 대조 4)"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0,
        help="인스턴스당 space-only CP-SAT 타임아웃(초, 기본 60)"
    )
    parser.add_argument(
        "--set", choices=["set1", "set2", "both", "custom"], default="both",
        help="대상 세트 (기본: both = set2 8 + set1 4)"
    )
    args = parser.parse_args()

    if args.probs is not None:
        target = args.probs
    elif args.set == "set1":
        target = DEFAULT_SET1
    elif args.set == "set2":
        target = DEFAULT_SET2
    else:  # both
        target = DEFAULT_SET2 + DEFAULT_SET1

    print(f"[z1_decomp] 대상: {target}", flush=True)
    print(f"[z1_decomp] space-only timeout/bay: {args.timeout}s", flush=True)
    print(f"[z1_decomp] ortools 사용 가능: {HAS_ORTOOLS}", flush=True)
    print()

    results = []
    for prob_num in target:
        print(f"--- prob_{prob_num} ---", flush=True)
        try:
            r = decompose_instance(prob_num, timeout_per_bay=args.timeout)
        except Exception as e:
            import traceback
            lines = traceback.format_exc().splitlines()
            short = "\n".join(lines[-5:])
            print(f"  EXCEPTION:\n{short}", flush=True)
            r = {"prob": prob_num, "error": str(e)}
        results.append(r)

        if "error" not in r:
            print(
                f"  full={r['full_z1']:,.0f}  space={r['space_only_z1']:,.0f}  "
                f"intr={r['intrinsic_z1']:,.0f}  "
                f"crane={r['crane_z1']:,.0f}({r['crane_pct']:.1f}%)  "
                f"wall={r['wall_s']}s",
                flush=True,
            )
        else:
            print(f"  ERROR: {r['error']}", flush=True)

    print_table(results)

    # JSON 저장
    out_path = os.path.join(V4, "z1_decomp_results.json")
    def _serial(r):
        rc = dict(r)
        if "bay_cpsat_status" in rc:
            rc["bay_cpsat_status"] = {str(k): v for k, v in rc["bay_cpsat_status"].items()}
        return rc
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([_serial(r) for r in results], f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}", flush=True)
