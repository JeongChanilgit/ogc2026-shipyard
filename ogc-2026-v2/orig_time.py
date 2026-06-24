"""orig_time.py — 원래솔버(solver_orig=../src/myalgorithm)가 timelimit 을 지키나 측정.

best-of 에서 원래솔버는 *in-process* 로 돌고 하드킬이 없다. 예산을 무시하고 폭주하면
서버(Linux)에서도 막을 게 없어 TIMEOUT → −1 위험. 여러 budget 으로 wall 측정.
실행: <env-python> orig_time.py [prob] [budgets...]   (기본 prob_34, 30 60)
"""
from __future__ import annotations

import os
import sys
import time
import json

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # orig_alg = ../src/myalgorithm.algorithm
from utils import check_feasibility   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def main():
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_34"
    budgets = [float(x) for x in sys.argv[2:]] or [30.0, 60.0]
    data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
    print(f"== 원래솔버 시간준수 [{nm}] N={len(data['blocks'])} bays={len(data['bays'])} ==", flush=True)
    for b in budgets:
        t0 = time.time()
        sol = ug.orig_alg(data, b)
        wall = time.time() - t0
        r = check_feasibility(data, sol)
        obj = r.get("objective") if isinstance(r, dict) else None
        over = wall - b
        flag = "  ⚠ 예산초과!" if over > 5 else ""
        print(f"  budget={b:>5.0f}s → wall={wall:>6.1f}s  (초과 {over:+.0f}s){flag}  "
              f"obj={obj:,}" if obj is not None else
              f"  budget={b:>5.0f}s → wall={wall:>6.1f}s  INFEAS", flush=True)


if __name__ == "__main__":
    main()
