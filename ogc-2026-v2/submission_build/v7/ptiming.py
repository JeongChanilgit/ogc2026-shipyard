"""
ptiming.py — 병렬 per-bay CP-SAT 타이밍 (사용자 통찰: 타이밍은 베이별 독립).

고정 레이아웃 위 최적 타이밍은 베이마다 독립(별도 크레인/공간) → 베이별 CP-SAT를
4코어 병렬로. wall ≈ max(베이별) (오라클의 순차·deadline분할 대비 ~베이수배 빠름).
각 베이는 작은 disjunctive라 짧은 캡으로도 수렴.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)

import utils  # noqa: E402
from utils import Bay, check_feasibility  # noqa: E402
from solver_orig import _cpsat_bay_timing_verified  # noqa: E402


def _bay_job(args):
    """베이 하나만 CP-SAT 재타이밍 → {block_id: (entry, exit)} | None."""
    inst, j, recs, per_bay_s = args
    data = json.load(open(inst, encoding="utf-8"))
    m = len(data["bays"])
    bays_objs = [Bay.from_dict(data["bays"][k], k) for k in range(m)]
    recs = {int(b): r for b, r in recs.items()}
    cand = _cpsat_bay_timing_verified(data, bays_objs, {j: recs},
                                      deadline=time.monotonic() + per_bay_s)
    if cand is None:
        return (j, None)
    et, xt = {}, {}
    for ts, opl in cand["operations"].items():
        for o in opl:
            if o["type"] == "ENTRY":
                et[o["block_id"]] = int(ts)
            else:
                xt[o["block_id"]] = int(ts)
    return (j, {b: (et[b], xt.get(b)) for b in et})


def parallel_timing(inst, data, results, per_bay_s=30.0, workers=4):
    """results{bay:{bid:rec}} 를 베이별 병렬 CP-SAT 재타이밍 후 공식 검증.
    return check_feasibility 결과 dict."""
    jobs = [(inst, j, results[j], per_bay_s) for j in results if results[j]]
    out = {}
    if jobs:
        try:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for (j, rt) in ex.map(_bay_job, jobs):
                    out[j] = rt
        except Exception:
            for jb in jobs:
                j, rt = _bay_job(jb)
                out[j] = rt
    # 재타이밍 적용 (베이가 개선 못했으면 None → 원래 시각 유지)
    for j, rt in out.items():
        if rt:
            for b, (e, x) in rt.items():
                if b in results[j] and e is not None and x is not None:
                    results[j][b]["entry_time"] = e
                    results[j][b]["exit_time"] = x
    # 전체 ops 재조립 (시간키 정렬 + EXIT 우선)
    ops = {}
    for j in results:
        for b, r in results[j].items():
            et, xt = str(int(r["entry_time"])), str(int(r["exit_time"]))
            ops.setdefault(et, []).append({"type": "ENTRY", "block_id": b, "bay_id": j,
                                           "x": r["x"], "y": r["y"], "orient_idx": r["orient_idx"]})
            ops.setdefault(xt, []).append({"type": "EXIT", "block_id": b, "bay_id": j})
    for t in ops:
        ops[t].sort(key=lambda o: 0 if o["type"] == "EXIT" else 1)
    ops_s = {k: ops[k] for k in sorted(ops, key=lambda s: int(s))}
    sol = {"operations": ops_s}
    r = check_feasibility(data, sol)
    if isinstance(r, dict):
        r["_solution"] = sol            # viz/디버그용 (검증엔 무관)
    return r


__all__ = ["parallel_timing"]
