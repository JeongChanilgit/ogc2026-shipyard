"""
cpsat_guideline.py — CP-SAT 배정 가이드라인 (z2·z3 전역 최소).

핵심: z2·z3 는 *배정만의 선형함수*(z1 무관). CP-SAT 가 전역 최적 배정을 준다.
  z3 = Σ_ij x_ij·(S_max_i − S_ij)          (정확 선형)
  z2 = max_j weighted_j − min_j weighted_j  (weighted_j = u_j·Σ workload),  minimax 변수
  목적: min  w2·z2 + w3·z3   (z1 은 그리디+오버플로가 처리)

`fixed`(이미 배치된 블록 {id: bay}) 를 받으면 그 부하/선호를 상수로 깔고 *남은 블록만*
최적화 → receding-horizon 재계획. CP-SAT 는 배정만 푸니 수 초로 빠름.

반환: guide[i] = 블록 i 가 가야 할 베이 (가이드라인). fixed 블록은 fixed 값 유지.
"""
from __future__ import annotations

import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

from ortools.sat.python import cp_model  # noqa: E402

U_SCALE = 100  # u_j 분수 → 정수화 배율


def _bbox_min_area(blocks, i):
    """블록 i 의 방향별 bbox 최소 면적 (area-time 용량용 풋프린트 프록시)."""
    best = None
    for o in range(len(blocks[i]["shape"])):
        xs = [p[0] for ly in blocks[i]["shape"][o]["layers"] for p in ly]
        ys = [p[1] for ly in blocks[i]["shape"][o]["layers"] for p in ly]
        a = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if best is None or a < best:
            best = a
    return best or 1.0


def _fit_bays(data):
    """블록별 bbox 가 들어가는 베이 목록 (어떤 방향이든 fit)."""
    bays, blocks = data["bays"], data["blocks"]
    m, N = len(bays), len(blocks)
    dims = [(b["width"], b["height"]) for b in bays]
    fit = []
    for i in range(N):
        bbs = []
        for o in range(len(blocks[i]["shape"])):
            xs = [p[0] for ly in blocks[i]["shape"][o]["layers"] for p in ly]
            ys = [p[1] for ly in blocks[i]["shape"][o]["layers"] for p in ly]
            bbs.append((max(xs) - min(xs), max(ys) - min(ys)))
        f = [j for j in range(m)
             if any(bw <= dims[j][0] + 1e-6 and bh <= dims[j][1] + 1e-6 for bw, bh in bbs)]
        fit.append(f or list(range(m)))
    return fit


def cpsat_guideline(data, fixed=None, time_s=8.0, fit=None, at_loose=None):
    """z2·z3 최소 배정 가이드라인 + area-time 용량 제약(packing-feasible 배정).
    fixed={id:bay} 는 상수로 고정. at_loose=베이 공정몫 대비 area-time 허용배율
    (기본 env OGC_GUIDE_ATLOOSE=1.15, 0=용량제약 끔). infeasible 시 자동 완화·해제."""
    fixed = dict(fixed or {})
    bays, blocks = data["bays"], data["blocks"]
    w = data["weights"]
    w2, w3 = w["w2"], w["w3"]
    m, N = len(bays), len(blocks)
    area = [b["width"] * b["height"] for b in bays]
    avg = sum(area) / m
    uj = [int(round((avg / a) * U_SCALE)) for a in area]   # u_j·U_SCALE
    wk = [int(blocks[i].get("workload", 0)) for i in range(N)]
    pr = [blocks[i]["bay_preferences"] for i in range(N)]
    smax = [max(p) for p in pr]
    if fit is None:
        fit = _fit_bays(data)
    if at_loose is None:
        at_loose = float(os.environ.get("OGC_GUIDE_ATLOOSE", "1.15"))
    free = [i for i in range(N) if i not in fixed]

    # area-time 수요 AT_i = bbox최소면적 · 처리시간, 베이 공정몫 = 면적비례
    AT = [int(round(_bbox_min_area(blocks, i) * blocks[i].get("processing_time", 0))) for i in range(N)]
    tot_AT = sum(AT) or 1
    tot_area = sum(area) or 1
    fixed_AT = [0] * m
    for i, j in fixed.items():
        fixed_AT[j] += AT[i]

    def build_and_solve(loose):
        model = cp_model.CpModel()
        x = {}
        for i in free:
            for j in fit[i]:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")
            model.AddExactlyOne([x[i, j] for j in fit[i]])
        # z2: weighted load minimax
        fixed_load = [0] * m
        for i, j in fixed.items():
            fixed_load[j] += wk[i]
        big = sum(uj[j] * (fixed_load[j] + sum(wk[i] for i in free)) for j in range(m)) + 1
        weighted = []
        for j in range(m):
            terms = [uj[j] * wk[i] * x[i, j] for i in free if (i, j) in x]
            weighted.append(uj[j] * fixed_load[j] + (sum(terms) if terms else 0))
        wmax = model.NewIntVar(0, big, "wmax")
        wmin = model.NewIntVar(0, big, "wmin")
        for wj in weighted:
            model.Add(wmax >= wj)
            model.Add(wmin <= wj)
        z2_scaled = wmax - wmin
        # z3
        z3_terms = [x[i, j] * (smax[i] - pr[i][j]) for i in free for j in fit[i] if (i, j) in x]
        z3_free = sum(z3_terms) if z3_terms else 0
        # area-time 용량: AT_j ≤ tot_AT·(area_j/tot_area)·loose
        if loose > 0:
            for j in range(m):
                cap = int(tot_AT * (area[j] / tot_area) * loose)
                terms = [AT[i] * x[i, j] for i in free if (i, j) in x]
                model.Add(fixed_AT[j] + (sum(terms) if terms else 0) <= cap)
        model.Minimize(w2 * z2_scaled + w3 * U_SCALE * z3_free)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_s)
        solver.parameters.num_workers = 4
        st = solver.Solve(model)
        ok = st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        return (solver, x, st, ok)

    # infeasible 면 용량 완화(×1.3) 후 해제까지 폴백
    loose = at_loose
    for _ in range(3):
        solver, x, st, ok = build_and_solve(loose)
        if ok:
            break
        loose = loose * 1.3 if loose > 0 else 0
        if loose > 0 and loose < 5:
            continue
        loose = 0  # 마지막: 용량 해제
    else:
        solver, x, st, ok = build_and_solve(0)

    guide = list(range(N))
    for i in range(N):
        guide[i] = fixed[i] if i in fixed else fit[i][0]
    if ok:
        for i in free:
            for j in fit[i]:
                if (i, j) in x and solver.Value(x[i, j]):
                    guide[i] = j
                    break
    return guide


def main():
    import json
    import time
    inst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        THIS, "..", "instances", "train", "prob_25.json")
    data = json.load(open(inst, encoding="utf-8"))
    w = data["weights"]
    t0 = time.time()
    g = cpsat_guideline(data, time_s=10.0)
    m = len(data["bays"])
    cnt = [g.count(j) for j in range(m)]
    print(f"{os.path.basename(inst)} w={w}  guideline dist={cnt}  ({time.time()-t0:.1f}s)")
    # z2/z3 확인
    from assign_search import z2 as _z2, z3 as _z3
    area = [b["width"] * b["height"] for b in data["bays"]]
    avg = sum(area) / m
    u = [avg / a for a in area]
    print(f"  z2={_z2(g, data['blocks'], u, m):.0f}  z3={_z3(g, data['blocks'])}")


if __name__ == "__main__":
    main()
