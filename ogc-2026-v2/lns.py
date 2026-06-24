"""lns.py — 유휴시간 LNS(파괴-재구성)로 base 해를 개선.

우리 해는 베이별 독립(크레인/공간 별개) → 한 베이만 재패킹+재타이밍하면 전체 재평가가 싸다.
매 반복: 최악 베이(w1·z1 최대) 선택 → 랜덤순서 재패킹 → 그 베이만 CP-SAT 재타이밍 →
전체 obj 개선시 채택(아니면 복귀). deadline 까지. weight-adaptive·실제 CP-SAT z1 판정.
"""
from __future__ import annotations

import json
import os
import random
import time

THIS = os.path.dirname(os.path.abspath(__file__))

from assign_search import build_set  # noqa: E402
from temporal_pack import simulate, seed_order  # noqa: E402
from ptiming import _bay_job  # noqa: E402

import utils as _utils  # noqa: E402


def _ops_and_obj(data, per_bay):
    """per_bay {j:{bid:rec}} → 전체 ops 재조립 + check_feasibility obj."""
    ops = {}
    for j in per_bay:
        for b, r in per_bay[j].items():
            et, xt = str(int(r["entry_time"])), str(int(r["exit_time"]))
            ops.setdefault(et, []).append({"type": "ENTRY", "block_id": b, "bay_id": j,
                                           "x": r["x"], "y": r["y"], "orient_idx": r["orient_idx"]})
            ops.setdefault(xt, []).append({"type": "EXIT", "block_id": b, "bay_id": j})
    for t in ops:
        ops[t].sort(key=lambda o: 0 if o["type"] == "EXIT" else 1)
    ops_s = {k: ops[k] for k in sorted(ops, key=lambda s: int(s))}
    sol = {"operations": ops_s}
    r = _utils.check_feasibility(data, sol)
    if isinstance(r, dict):
        r["_solution"] = sol
    return r


def _bay_z1(per_bay_j, blocks):
    return sum(max(0, r["exit_time"] - blocks[r["block_id"]]["due_date"])
               for r in per_bay_j.values())


def lns_improve(inst, data, per_bay, assign, deadline, per_bay_s, fit="1", rng_seed=12345):
    """per_bay(베이별 {bid:rec}) 를 LNS 로 개선 → (best_per_bay, best_result)."""
    blocks, bays = data["blocks"], data["bays"]
    w1 = data["weights"]["w1"]
    dims = [(b["width"], b["height"]) for b in bays]
    rng = random.Random(rng_seed)
    best = {j: dict(per_bay[j]) for j in per_bay}
    best_res = _ops_and_obj(data, best)
    best_obj = best_res.get("objective")
    if best_obj is None:
        return per_bay, best_res
    it = accept = 0
    while time.time() < deadline:
        it += 1
        # 최악 베이 = w1·z1 최대 (블록 2+ 인 베이 중)
        cand = [j for j in best if len(best[j]) >= 2]
        if not cand:
            break
        j = max(cand, key=lambda jj: _bay_z1(best[jj], blocks))
        if _bay_z1(best[j], blocks) == 0 and rng.random() < 0.5:
            j = rng.choice(cand)                       # z1=0 이면 가끔 랜덤 베이
        ids = list(best[j].keys())
        # 파괴+재구성: 랜덤 순서로 재패킹
        sub = build_set(blocks, dims[j][0], dims[j][1], ids, 2)
        order = seed_order(sub, "edd")
        rng.shuffle(order)
        placed, _ = simulate(sub, order, allow_stack=False, fit=fit)
        recs = {p["id"]: {"block_id": p["id"], "bay_id": j, "x": p["x"], "y": p["y"],
                          "orient_idx": p["orient"], "entry_time": p["entry"],
                          "exit_time": p["exit"]} for p in placed}
        if len(recs) != len(ids):
            continue
        # 그 베이만 CP-SAT 재타이밍 (LNS 는 작은 캡 = 많은 반복)
        cap_it = float(os.environ.get("OGC_LNS_CAP", "8"))
        try:
            _, rt = _bay_job((inst, j, recs, min(cap_it, max(3.0, deadline - time.time()))))
        except Exception:
            rt = None
        if rt:
            for b, (e, x) in rt.items():
                if b in recs and e is not None and x is not None:
                    recs[b]["entry_time"], recs[b]["exit_time"] = e, x
        # 전체 obj 평가 (다른 베이 그대로)
        trial = {jj: (recs if jj == j else best[jj]) for jj in best}
        res = _ops_and_obj(data, trial)
        obj = res.get("objective")
        if obj is not None and obj < best_obj - 1e-9:
            best[j], best_obj, best_res = recs, obj, res
            accept += 1
    print(f"[LNS] {it} iters, {accept} accepts, obj→{best_obj:,.0f}", flush=True)
    return best, best_res


__all__ = ["lns_improve"]
