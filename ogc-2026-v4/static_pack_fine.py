"""
static_pack_fine.py — fine-resolution greedy BL 패커로 정적 피크패킹 상한 측정

질문: z1-worst 베이의 경합집합 S(시간 무시)를 빈 베이에 동시에 겹침없이
     최대 몇 개나 끼울 수 있나?
     거친 40후보 CP-SAT가 모호했으니 → 정수 전해상도 BL greedy로 확정.

패킹 방법:
  1. S의 블록을 면적 내림차순 정렬
  2. 각 블록: 모든 방향 × 정수(x,y) 전수 → bottom-left(y작→x작) 첫 가능 위치 배치
  3. BayGrid.can_coexist() = 비트맵 사전필터 + shapely 정확검증 (정적: 크레인 무시)

판정 기준:
  F ≈ |S|       → 패킹 레버 도달가능 (우리 BL이 약함, z1 개선 여지 = F-M)
  F ≈ M (~30)   → 폴리곤 모양 벽 확정 = z1 구조적 → z3 피벗
  중간           → 부분 개선

대상: prob_38, 40, 27

실행:
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe static_pack_fine.py
  C:/Users/peter/anaconda3/envs/ogc2025/python.exe static_pack_fine.py --probs 38 40 27
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
V4 = os.path.dirname(os.path.abspath(__file__))
INST_DIR = os.path.normpath(os.path.join(V4, "..", "instances", "train"))

if V4 not in sys.path:
    sys.path.insert(0, V4)

# peak_pack_test.py 에서 재사용할 두 함수만 임포트
from peak_pack_test import find_worst_bay, find_peak_coexistence  # noqa: E402
from gridmap import BayGrid, build_shape, BlockShape               # noqa: E402

# ---------------------------------------------------------------------------
# 로드
# ---------------------------------------------------------------------------

def load_instance_and_solution(prob_num: int):
    inst_path = os.path.join(INST_DIR, f"prob_{prob_num}.json")
    sol_path  = os.path.join(V4, f"real_prob_{prob_num}.json")
    data = json.load(open(inst_path, encoding="utf-8"))
    sol  = json.load(open(sol_path,  encoding="utf-8"))
    return data, sol


# ---------------------------------------------------------------------------
# 면적 통계
# ---------------------------------------------------------------------------

def compute_area_pct(data: dict, bay_id: int, block_ids: List[int]) -> float:
    """Compute total footprint area of block_ids as % of bay area.

    build_shape returns shapely polygons in world (bay) coordinates regardless of scale.
    footprint_area = poly.area = actual area in world units. No scale correction needed.
    """
    bay_data = data["bays"][bay_id]
    W = int(bay_data["width"])
    H = int(bay_data["height"])
    bay_area = W * H
    blocks_data = data["blocks"]
    total = 0.0
    for bid in block_ids:
        sh = build_shape(bid, blocks_data[bid], 0, scale=2)
        total += sh.footprint_area   # shapely poly.area in world units (no scale divisor)
    return (total / bay_area * 100.0) if bay_area > 0 else 0.0


# ---------------------------------------------------------------------------
# Fine-resolution BL greedy 패커
# ---------------------------------------------------------------------------

def fine_greedy_pack(data: dict, bay_id: int, block_ids: List[int],
                     scale: int = 2, exact: bool = True) -> Tuple[int, List]:
    """
    block_ids (경합집합) 을 빈 베이에 greedy BL로 배치.
    크레인 제약 없음 (정적 패킹: can_coexist 사용).

    Returns:
        (count, placements)   count = 배치된 블록 수
        placements = [(bid, x, y, orient_idx), ...]
    """
    bay_data    = data["bays"][bay_id]
    W           = int(bay_data["width"])
    H           = int(bay_data["height"])
    blocks_data = data["blocks"]

    # 레이어 최대 수 파악
    max_layer = 1
    shapes_by_block: Dict[int, List[BlockShape]] = {}
    for bid in block_ids:
        bdata = blocks_data[bid]
        n_orients = len(bdata["shape"])
        shs = [build_shape(bid, bdata, o, scale=scale) for o in range(n_orients)]
        shapes_by_block[bid] = shs
        for sh in shs:
            max_layer = max(max_layer, sh.n_layers)

    grid = BayGrid(W, H, max_layer, scale=scale, exact=exact)

    # 면적 내림차순 정렬 (큰 블록 먼저 → 더 많이 끼움)
    order = sorted(block_ids,
                   key=lambda b: -shapes_by_block[b][0].footprint_area)

    placements = []

    for bid in order:
        placed = False
        for sh in shapes_by_block[bid]:
            # x, y 정수 전수 범위
            x_lb = max(0, int(math.ceil(-sh.min_x - 1e-9)))
            x_ub = max(x_lb, int(math.floor(W - sh.max_x + 1e-9)))
            y_lb = max(0, int(math.ceil(-sh.min_y - 1e-9)))
            y_ub = max(y_lb, int(math.floor(H - sh.max_y + 1e-9)))

            # BL 순서: y 오름차순 → x 오름차순
            for y in range(y_lb, y_ub + 1):
                for x in range(x_lb, x_ub + 1):
                    if grid.can_coexist(sh, x, y, check_bounds=True):
                        grid.place(sh, x, y)
                        placements.append((bid, x, y, sh.orient_idx))
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break

    return grid.n_placed, placements


# ---------------------------------------------------------------------------
# 단일 인스턴스 처리
# ---------------------------------------------------------------------------

def run_instance(prob_num: int, verbose: bool = True) -> dict:
    t0 = time.monotonic()

    try:
        data, sol = load_instance_and_solution(prob_num)
    except FileNotFoundError as e:
        return {"prob": prob_num, "error": str(e)}

    # worst bay
    worst_bay, bay_z1 = find_worst_bay(data, sol)

    # 경합집합 추출
    t_star, S_ideal, S_actual, M_actual = find_peak_coexistence(data, sol, worst_bay)
    S_sz = len(S_ideal)

    if not S_ideal:
        return {"prob": prob_num, "error": "경합집합 추출 실패"}

    area_pct = compute_area_pct(data, worst_bay, S_ideal)

    if verbose:
        print(f"  prob_{prob_num}: worst_bay={worst_bay}, bay_z1={bay_z1:.0f}, "
              f"|S|={S_sz}, area={area_pct:.1f}%, M={M_actual}", flush=True)
        print(f"  -> fine greedy packing ...", flush=True)

    # Fine greedy
    t_pack = time.monotonic()
    F, placements = fine_greedy_pack(data, worst_bay, S_ideal,
                                     scale=2, exact=True)
    pack_wall = time.monotonic() - t_pack
    total_wall = time.monotonic() - t0

    if verbose:
        print(f"  -> F={F} (wall={pack_wall:.1f}s, total={total_wall:.1f}s)", flush=True)

    return {
        "prob":        prob_num,
        "worst_bay":   worst_bay,
        "bay_z1":      bay_z1,
        "t_star":      t_star,
        "S_size":      S_sz,
        "area_pct":    round(area_pct, 1),
        "M_actual":    M_actual,
        "N_coarse":    {"38": 33, "40": 24, "27": 30}.get(str(prob_num), None),
        "F_fine":      F,
        "gap_FM":      F - M_actual,       # F - M: 우리 대비 fine 패커 이득
        "pack_wall_s": round(pack_wall, 1),
        "total_wall_s": round(total_wall, 1),
    }


# ---------------------------------------------------------------------------
# 결과 출력
# ---------------------------------------------------------------------------

def print_results(results: list):
    # coarse CP-SAT N reference values (from prior peak_pack_test run)
    N_coarse_ref = {38: 33, 40: 24, 27: 30}

    print()
    print("=" * 105)
    print("[ static_pack_fine - fine-resolution greedy BL packing ]")
    print("  no crane constraint, spatial (no same-layer overlap) only.")
    print("  Q: max blocks from peak coexistence set S packed into empty bay?")
    print("=" * 105)

    hdr = (
        f"{'prob':>6} | {'bay_z1':>9} | "
        f"{'|S|':>4} {'area%':>7} | "
        f"{'M_ours':>6} {'N_coarse':>8} {'F_fine':>7} | "
        f"{'F-M':>5} {'F-N':>5} | "
        f"{'verdict':>30} | "
        f"{'time':>5}"
    )
    print(hdr)
    print("-" * 105)

    valid = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    for r in valid:
        N_c = N_coarse_ref.get(r["prob"], r.get("N_coarse"))
        N_c_str = str(N_c) if N_c is not None else "  ?"
        F = r["F_fine"]
        S = r["S_size"]
        M = r["M_actual"]
        gap_FM = F - M
        gap_FN = (F - N_c) if N_c is not None else None
        gap_FN_str = f"{gap_FN:+d}" if gap_FN is not None else "  ?"

        if F >= S:
            verdict = "LEVER CONFIRMED (F>=|S|)"
        elif F > M:
            pct = (F - M) / max(1, S - M) * 100
            verdict = f"partial lever +{F-M} ({pct:.0f}% gap closed)"
        elif F == M:
            verdict = "POLY WALL structural (F=M)"
        else:
            verdict = f"WORSE than ours (F={F}<M={M})"

        row = (
            f"{r['prob']:>6} | {r['bay_z1']:>9,.0f} | "
            f"{S:>4} {r['area_pct']:>6.1f}% | "
            f"{M:>6} {N_c_str:>8} {F:>7} | "
            f"{gap_FM:>+5} {gap_FN_str:>5} | "
            f"{verdict:>30} | "
            f"{r['total_wall_s']:>4.0f}s"
        )
        print(row)

    for r in errors:
        print(f"  prob_{r['prob']}: ERROR {r['error']}")

    print()
    print("=" * 105)
    print("[ KEY VERDICT ]")
    print()

    for r in valid:
        S = r["S_size"]
        M = r["M_actual"]
        F = r["F_fine"]
        N_c = N_coarse_ref.get(r["prob"])
        gap_FM = F - M

        print(f"  prob_{r['prob']} (worst bay={r['worst_bay']}, area%={r['area_pct']}% of bay):")
        print(f"    |S|={S}  M_ours={M}  N_coarse_CPSAT={N_c}  F_fine={F}")

        if F >= S:
            print(f"    *** LEVER CONFIRMED: fine packer fits all {S} blocks!")
            print(f"        Our solver places only {M} simultaneously -> {F-M} blocks wastefully serialized")
            print(f"        => Denser initial layout can eliminate most z1")
            print(f"        => Explains competitor z1~=0: their packer is superior")
        elif F > M:
            pct_closed = (F - M) / max(1, S - M) * 100
            print(f"    PARTIAL: fine F={F} > ours M={M}, gap improvement {gap_FM:+d} ({pct_closed:.0f}% closed)")
            if F >= S * 0.8:
                print(f"        => Substantial packing lever. Better packer can improve z1.")
            else:
                print(f"        => Limited lever. Polygon shapes constrain significantly.")
        elif F == M:
            print(f"    POLY WALL: fine packer also F=M={M}, no improvement")
            print(f"        => z1 is structural polygon-shape wall. Pivot to z3.")
        else:
            print(f"    *** CONFIRMED WORSE: fine greedy F={F} < our M={M}")
            print(f"        => Our solver's co-presence is already at/above greedy ceiling")
            print(f"        => area% of S = {r['area_pct']}% >> bay capacity")
            print(f"        => z1 is caused by CRANE SERIALIZATION, not packing density")
            print(f"        => S blocks' total area EXCEEDS bay -> structural ceiling confirmed")
            print(f"        => Cannot fit |S|={S} blocks regardless of packer quality")
            print(f"        => z1 = co-presence BOUND, NOT a packing lever -> pivot to z3/crane-repack")
        print()

    if valid:
        total_gap_FM = sum(r["gap_FM"] for r in valid)
        lever_probs = [r["prob"] for r in valid if r["F_fine"] >= r["S_size"]]
        worse_probs = [r["prob"] for r in valid if r["F_fine"] < r["M_actual"]]
        same_probs  = [r["prob"] for r in valid if r["F_fine"] == r["M_actual"]]
        partial_probs = [r["prob"] for r in valid
                        if r["M_actual"] < r["F_fine"] < r["S_size"]]

        print("  [ SUMMARY ]")
        if lever_probs:
            print(f"  Packing lever CONFIRMED: {lever_probs}")
        if partial_probs:
            print(f"  Partial packing lever:   {partial_probs}")
        if same_probs:
            print(f"  Structural poly wall:    {same_probs}")
        if worse_probs:
            print(f"  Fine packer < ours (z1=co-presence bound): {worse_probs}")
        print(f"  Total F-M across tested probs: {total_gap_FM:+d} blocks")
        print()
        if worse_probs or same_probs:
            print("  FINAL VERDICT: z1 is structural co-presence bound.")
            print("    S-blocks total area > bay capacity -> cannot all coexist spatially.")
            print("    Packing lever FALSIFIED for these instances.")
            print("    => z3 pivot is the correct direction, not packing density.")
        if lever_probs:
            print("  FINAL VERDICT: Packing lever is REAL for some instances.")
            print("    Denser layout algorithm would reduce z1 for those.")
    print("=" * 105)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

DEFAULT_TARGETS = [38, 40, 27]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="fine-resolution BL greedy 정적 피크패킹")
    parser.add_argument("--probs", nargs="+", type=int, default=None)
    args = parser.parse_args()

    targets = args.probs if args.probs else DEFAULT_TARGETS

    print(f"[static_pack_fine] targets: {targets}", flush=True)
    print(f"[static_pack_fine] fine greedy BL, integer full-resolution, exact shapely verify", flush=True)
    print()

    results = []
    for prob_num in targets:
        print(f"\n{'='*50}", flush=True)
        print(f"  prob_{prob_num}", flush=True)
        print(f"{'='*50}", flush=True)
        try:
            r = run_instance(prob_num, verbose=True)
        except Exception as e:
            import traceback
            lines = traceback.format_exc().splitlines()
            short = "\n".join(lines[-5:])
            print(f"  EXCEPTION:\n{short}", flush=True)
            r = {"prob": prob_num, "error": str(e)}
        results.append(r)

    print_results(results)

    out_path = os.path.join(V4, "static_pack_fine_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}", flush=True)
