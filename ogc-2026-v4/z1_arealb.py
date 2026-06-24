"""
z1_arealb.py -- area-relaxed lower bound for z1 (tardiness)

정의 (면적-완화 LB):
  고정 배정(베이 소속)은 유지하되 폴리곤 모양/위치를 완전히 무시.
  각 블록을 (area_i, R_i, P_i, due_i) 로 추상화.
  CP-SAT AddCumulative 로 면적 용량만 건 최소 tardiness 구함.

  AddCumulative(intervals, demands=area_i, capacity=bay_area):
    어느 시점 t 에서도 활성 블록들의 area 합 ≤ bay_area.
    minimize Σ max(0, (entry_i + P_i) - due_i)

  area_LB ≤ true_min_z1 ≤ full_z1  (완화이므로 항상 성립)

해석:
  full_z1 - area_LB = "패킹-addressable" (패킹 레이아웃 개선으로 줄일 수 있는 여지)
  area_LB           = "면적-구조적" (베이 용량 자체 한계, 어떤 레이아웃도 못 줄임)

실행:
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe z1_arealb.py
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe z1_arealb.py --probs 38 40 27
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe z1_arealb.py --timeout 90
"""
from __future__ import annotations

import json
import os
import sys
import time
import argparse
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
V4 = os.path.dirname(os.path.abspath(__file__))
INST_DIR = os.path.normpath(os.path.join(V4, "..", "instances", "train"))

if V4 not in sys.path:
    sys.path.insert(0, V4)

import utils as _utils  # noqa
from adapter import deserialize  # noqa
import gridmap  # noqa

# ---------------------------------------------------------------------------
# OR-Tools CP-SAT
# ---------------------------------------------------------------------------
try:
    from ortools.sat.python import cp_model
    HAS_ORTOOLS = True
except ImportError:
    HAS_ORTOOLS = False
    print("[WARN] ortools 없음 — 휴리스틱 폴백 사용", flush=True)


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
# 블록 면적 추출 (scale=2, 방향 무관)
# ---------------------------------------------------------------------------
def _block_footprint_area(data: dict, bid: int) -> float:
    """폴리곤 기반 풋프린트 면적 (scale=2, 방향 0 기준 — 방향 무관하게 동일)."""
    blk = data["blocks"][bid]
    sh = gridmap.build_shape(bid, blk, 0, scale=2)
    return float(sh.footprint_area)


def _bay_area(data: dict, bay_id: int) -> int:
    """베이 면적 (scale=2 좌표계). W*2 * H*2."""
    bay = data["bays"][bay_id]
    return int(bay["width"]) * 2 * int(bay["height"]) * 2


# ---------------------------------------------------------------------------
# 배정 추출: solution → {bay_id: [bid, ...]}
# ---------------------------------------------------------------------------
def _extract_assignments(sol: dict) -> Dict[int, List[int]]:
    bay_blocks: Dict[int, List[int]] = {}
    for t_str, ops in sol["operations"].items():
        for op in ops:
            if op["type"] == "ENTRY":
                j = int(op["bay_id"])
                b = int(op["block_id"])
                bay_blocks.setdefault(j, []).append(b)
    return bay_blocks


# ---------------------------------------------------------------------------
# area-relaxed LB per bay (CP-SAT AddCumulative)
# ---------------------------------------------------------------------------
def _area_lb_bay_cpsat(
    data: dict,
    bay_id: int,
    block_ids: List[int],
    timeout_s: float = 90.0,
) -> Tuple[float, float, str]:
    """
    면적-완화 타디니스 하한 (베이 단위).

    Returns:
        (best_feasible, proven_lb, status_str)
        best_feasible : CP-SAT 이 찾은 최선 feasible 목적값 (상한이자 여유 증명)
        proven_lb     : CP-SAT 이 증명한 하한 (OPTIMAL 이면 = best_feasible)
        status_str    : "OPTIMAL" / "FEASIBLE" / "HEURISTIC" 등
    """
    if not block_ids:
        return 0.0, 0.0, "EMPTY"

    blocks = data["blocks"]
    bay_cap = _bay_area(data, bay_id)  # scale=2 면적 용량

    n = len(block_ids)
    R = [int(blocks[b]["release_time"]) for b in block_ids]
    P = [int(blocks[b]["processing_time"]) for b in block_ids]
    due = [int(blocks[b]["due_date"]) for b in block_ids]
    # 면적 정수화 (CP-SAT 는 정수만; round to nearest int, floor >= 1)
    areas_raw = [_block_footprint_area(data, b) for b in block_ids]
    # CP-SAT AddCumulative 는 정수여야 함 → ×100 스케일링
    AREA_SCALE = 100
    areas_int = [max(1, round(a * AREA_SCALE)) for a in areas_raw]
    cap_int = int(bay_cap * AREA_SCALE)

    t_max = max(R[i] + P[i] for i in range(n)) + sum(P) + 1

    if not HAS_ORTOOLS:
        # 휴리스틱: EDD 직렬화 (면적 제약 완화한 하한 ≈ intrinsic LB)
        total = sum(max(0, R[i] + P[i] - due[i]) for i in range(n))
        return float(total), float(total), "HEURISTIC_INTRINSIC"

    model = cp_model.CpModel()

    # 결정변수: entry_i
    entry_vars = [model.NewIntVar(R[i], t_max, f"e{i}") for i in range(n)]
    # interval_i = [entry_i, entry_i + P_i]
    interval_vars = [
        model.NewFixedSizeIntervalVar(entry_vars[i], P[i], f"iv{i}")
        for i in range(n)
    ]

    # AddCumulative: 어느 시점에서도 Σ area_i ≤ bay_capacity
    model.AddCumulative(interval_vars, areas_int, cap_int)

    # entry_i >= R_i 는 NewIntVar lb 로 이미 보장됨

    # tardiness vars
    tard_vars = []
    for i in range(n):
        exit_i = model.NewIntVar(R[i] + P[i], t_max, f"ex{i}")
        model.Add(exit_i == entry_vars[i] + P[i])
        tard = model.NewIntVar(0, t_max, f"t{i}")
        model.AddMaxEquality(tard, [exit_i - due[i], model.NewConstant(0)])
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
        best = float(solver.ObjectiveValue())
        lb = float(solver.BestObjectiveBound())
        return best, lb, status_str
    else:
        # intrinsic LB as fallback
        intr = sum(max(0, R[i] + P[i] - due[i]) for i in range(n))
        return float(intr), float(intr), f"{status_str}→INTRINSIC_LB"


# ---------------------------------------------------------------------------
# 전체 인스턴스 처리
# ---------------------------------------------------------------------------
def compute_area_lb(
    prob_num: int,
    timeout_per_bay: float = 90.0,
) -> dict:
    t0 = time.monotonic()

    try:
        data, sol = load_instance_and_solution(prob_num)
    except FileNotFoundError as e:
        return {"prob": prob_num, "error": str(e)}

    blocks = data["blocks"]
    weights = data["weights"]
    w1 = weights["w1"]

    # 공식 full z1
    try:
        r = _utils.check_feasibility(data, sol)
        full_z1 = float(r.get("obj1") or 0)
        feasible = (r.get("objective") is not None) and (len(r.get("violations", [])) == 0)
    except Exception as e:
        return {"prob": prob_num, "error": f"full_z1 실패: {e}"}

    if not feasible:
        return {"prob": prob_num, "error": "infeasible solution"}

    # 배정 추출
    bay_blocks = _extract_assignments(sol)

    # 베이별 area_LB 계산
    total_best = 0.0
    total_proven = 0.0
    bay_results = {}

    for bay_id, bids in sorted(bay_blocks.items()):
        bbudget = timeout_per_bay  # per-bay budget
        best, lb, st = _area_lb_bay_cpsat(data, bay_id, bids, timeout_s=bbudget)
        total_best += best
        total_proven += lb
        bay_results[bay_id] = {"best": best, "lb": lb, "status": st, "n_blocks": len(bids)}

    wall = time.monotonic() - t0

    # 패킹-addressable (full z1 - area_LB best feasible)
    pack_addressable = max(0.0, full_z1 - total_best)
    area_structural = total_best  # = area_LB (best feasible)
    pack_pct = (pack_addressable / full_z1 * 100) if full_z1 > 0 else 0.0
    struct_pct = (area_structural / full_z1 * 100) if full_z1 > 0 else 0.0

    return {
        "prob": prob_num,
        "feasible": feasible,
        "w1": w1,
        "full_z1": full_z1,
        "area_lb_best": total_best,       # best feasible (여유 증명)
        "area_lb_proven": total_proven,   # CP-SAT proven lower bound
        "pack_addressable": pack_addressable,
        "pack_pct": pack_pct,
        "struct_pct": struct_pct,
        "bay_results": bay_results,
        "wall_s": round(wall, 1),
        # 상태 요약
        "statuses": {str(j): v["status"] for j, v in bay_results.items()},
    }


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def print_table(results: list):
    valid = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    print()
    print("=" * 110)
    print("[ z1 area-relaxed Lower Bound: 패킹 레버 vs 면적-구조적 한계 ]")
    print("=" * 110)

    hdr = (
        f"{'prob':>6} | {'full_z1':>9} {'area_LB':>9} {'proven_LB':>9} | "
        f"{'pack_addr':>10} {'pack%':>6} | {'struct':>9} {'struct%':>7} | "
        f"{'w1':>8} {'wall':>5} | notes"
    )
    print(hdr)
    print("-" * 110)

    for r in valid:
        # notes: OPTIMAL 여부
        statuses = list(r.get("statuses", {}).values())
        n_opt = sum(1 for s in statuses if s == "OPTIMAL")
        n_tot = len(statuses)
        notes = f"OPT {n_opt}/{n_tot}"
        if r["area_lb_best"] > r["area_lb_proven"] + 0.5:
            notes += f" gap={r['area_lb_best']-r['area_lb_proven']:.0f}"

        row = (
            f"{r['prob']:>6} | "
            f"{r['full_z1']:>9,.0f} "
            f"{r['area_lb_best']:>9,.0f} "
            f"{r['area_lb_proven']:>9,.0f} | "
            f"{r['pack_addressable']:>10,.0f} "
            f"{r['pack_pct']:>5.1f}% | "
            f"{r['area_lb_best']:>9,.0f} "
            f"{r['struct_pct']:>6.1f}% | "
            f"{r['w1']:>8,} "
            f"{r['wall_s']:>4.0f}s | {notes}"
        )
        print(row)

    if errors:
        print()
        print("[ 에러 ]")
        for r in errors:
            print(f"  prob_{r['prob']}: {r['error']}")

    # 합계 분리
    set2 = [r for r in valid if r["prob"] >= 21]
    set1 = [r for r in valid if r["prob"] <= 20]

    print()
    print("=" * 110)
    print("[ 합계 ]")
    for label, subset in [("set2", set2), ("set1", set1), ("전체", valid)]:
        if not subset:
            continue
        sf = sum(r["full_z1"] for r in subset)
        sb = sum(r["area_lb_best"] for r in subset)
        sp = sum(r["area_lb_proven"] for r in subset)
        sa = sum(r["pack_addressable"] for r in subset)
        d = sf if sf > 0 else 1.0
        print(f"  {label}: full_z1={sf:,.0f} | "
              f"area_LB(best)={sb:,.0f} ({sb/d*100:.1f}%) "
              f"area_LB(proven)={sp:,.0f} ({sp/d*100:.1f}%) | "
              f"pack_addr={sa:,.0f} ({sa/d*100:.1f}%)")

    # 판정 (set2 기준)
    if set2:
        sf = sum(r["full_z1"] for r in set2)
        sb = sum(r["area_lb_best"] for r in set2)
        sa = sum(r["pack_addressable"] for r in set2)
        d = sf if sf > 0 else 1.0

        print()
        print("=" * 110)
        print("[ 핵심 판정 ]")
        print(f"  set2 z1 합계      = {sf:,.0f}")
        print(f"  면적-구조적 (LB)  = {sb:,.0f} ({sb/d*100:.1f}%)  ← 어떤 레이아웃도 줄일 수 없는 하한")
        print(f"  패킹-addressable  = {sa:,.0f} ({sa/d*100:.1f}%)  ← 완벽한 레이아웃이 잡을 수 있는 상한")
        print()

        if sa / d > 0.30:
            print("  판정: 패킹-addressable > 30%")
            print("    → 면적 여유 존재. 더 조밀한 레이아웃(경쟁자 수준)으로 z1 감소 가능.")
            top3 = sorted(set2, key=lambda r: -r["pack_addressable"])[:3]
            print("    가장 여유 큰 인스턴스 (pack_addressable 절대값 순):")
            for r in top3:
                print(f"      prob_{r['prob']}: pack_addr={r['pack_addressable']:,.0f} ({r['pack_pct']:.1f}% of full_z1)")
        elif sa / d > 0.10:
            print("  판정: 패킹-addressable 10~30%")
            print("    → 면적 여유 소폭 존재. 패킹 개선은 제한적 효과.")
        else:
            print("  판정: 패킹-addressable < 10%")
            print("    → z1 은 면적-구조적. 패킹으로 줄이기 어려움.")
            print("    → z3(선호도) 피벗 권고.")

    print("=" * 110)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
DEFAULT_TARGETS = [38, 40, 27, 33, 37, 39, 32, 26, 29, 14, 20]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="z1 area-relaxed lower bound")
    parser.add_argument(
        "--probs", nargs="+", type=int, default=None,
        help="대상 인스턴스 번호 (기본: 11개)"
    )
    parser.add_argument(
        "--timeout", type=float, default=90.0,
        help="베이당 CP-SAT 타임아웃(초, 기본 90)"
    )
    args = parser.parse_args()

    target = args.probs if args.probs is not None else DEFAULT_TARGETS

    print(f"[z1_arealb] 대상: {target}", flush=True)
    print(f"[z1_arealb] bay 당 timeout: {args.timeout}s", flush=True)
    print(f"[z1_arealb] ortools: {HAS_ORTOOLS}", flush=True)
    print()

    results = []
    for prob_num in target:
        print(f"--- prob_{prob_num} ---", flush=True)
        t0 = time.monotonic()
        try:
            r = compute_area_lb(prob_num, timeout_per_bay=args.timeout)
        except Exception as e:
            import traceback
            lines = traceback.format_exc().splitlines()
            short = "\n".join(lines[-5:])
            print(f"  EXCEPTION:\n{short}", flush=True)
            r = {"prob": prob_num, "error": str(e)}
        results.append(r)

        if "error" not in r:
            print(
                f"  full_z1={r['full_z1']:,.0f}  "
                f"area_LB={r['area_lb_best']:,.0f}(proven={r['area_lb_proven']:,.0f})  "
                f"pack_addr={r['pack_addressable']:,.0f}({r['pack_pct']:.1f}%)  "
                f"wall={r['wall_s']}s",
                flush=True,
            )
        else:
            print(f"  ERROR: {r['error']}", flush=True)

    print_table(results)

    # JSON 저장
    out_path = os.path.join(V4, "z1_arealb_results.json")

    def _serial(r):
        rc = dict(r)
        if "bay_results" in rc:
            rc["bay_results"] = {str(k): v for k, v in rc["bay_results"].items()}
        return rc

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([_serial(r) for r in results], f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}", flush=True)
