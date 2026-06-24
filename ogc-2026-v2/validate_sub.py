"""validate_sub.py — 재빌드한 제출 zip(submission_build) 격리 검증.

myalgorithm.algorithm(=배포 best-of, v2 GLOBAL=1 최우선) 을 set1+set2 인스턴스에 돌려
feasible·시간내·objective 확인. exp_submission.run(서버모사 subprocess) 재사용.
실행: <env-python> validate_sub.py [TL] [prob ...]
"""
from __future__ import annotations

import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from exp_submission import run, TRAIN   # noqa: E402


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    names = sys.argv[2:] or ["prob_1", "prob_14", "prob_27", "prob_38"]
    print(f"== 제출 zip 격리 검증 @TL={tl}s (v2 GLOBAL=1 최우선 + best-of) ==", flush=True)
    ok = 0
    for nm in names:
        inst = os.path.join(TRAIN, nm + ".json")
        r = run(inst, tl, "1")
        obj = r.get("obj")
        wall = r.get("wall")
        feas = obj is not None
        over = wall is not None and wall > tl + 3
        ok += int(feas and not over)
        sett = "set1" if (nm.split("_")[-1].isdigit() and int(nm.split("_")[1]) <= 20) else "set2"
        print(f"  [{sett}] {nm:9s} {'FEASIBLE' if feas else 'INFEAS/'+str(r.get('stage'))}  "
              f"obj={obj if obj is None else f'{obj:,.0f}'}  z1={r.get('z1')} z2={r.get('z2')} z3={r.get('z3')}"
              f"  wall={wall}s {'⚠TL초과!' if over else 'OK'}", flush=True)
    print(f"\n  → {ok}/{len(names)} feasible & 시간내. {'✅ 제출 가능' if ok == len(names) else '⚠ 확인필요'}",
          flush=True)


if __name__ == "__main__":
    main()
