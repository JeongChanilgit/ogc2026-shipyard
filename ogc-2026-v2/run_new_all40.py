"""run_new_all40.py — NEW 제출(best-of, OGC_GLOBAL=1) ALL40 @TL 단일 실행 + 저장.

배포 zip 과 동일 best-of(v2,원래,baseline) 구조, v2 엔진만 전역 Pass B(OGC_GLOBAL=1).
결과 results/bestof_global1_all40_tl<TL>.json 에 인스턴스마다 증분 저장(중단 안전).
비교 기준: v2-단독-g0 = out/all40_fit1.json (239.27M, set1 13.96M / set2 225.31M);
          배포 best-of set2 ≈ 225.31M (v2 가 set2 best-of 승).
실행(env-python 직접): <env-python> run_new_all40.py [TL] [prob_X ...]
"""
from __future__ import annotations

import os
import sys
import json

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from exp_submission import run, TRAIN   # noqa: E402  (best-of subprocess 실행기 재사용)

RES = os.path.join(THIS, "results")


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    names = sys.argv[2:] or [f"prob_{i}" for i in range(1, 41)]
    os.makedirs(RES, exist_ok=True)
    outp = os.path.join(RES, f"bestof_global1_all40_tl{int(tl)}.json")
    print(f"== NEW 제출 best-of(OGC_GLOBAL=1) ALL40 @TL={tl}s ==  저장→{outp}", flush=True)
    rows, total, feas, minus1, s1, s2, maxwall = [], 0.0, 0, 0, 0.0, 0.0, 0.0
    for nm in names:
        inst = os.path.join(TRAIN, nm + ".json")
        data = json.load(open(inst, encoding="utf-8"))
        r = run(inst, tl, "1")
        ob = r.get("obj")
        num = int(nm.split("_")[1]) if nm.split("_")[-1].isdigit() else 99
        sett = "set1" if num <= 20 else "set2"
        maxwall = max(maxwall, r.get("wall") or 0)
        if ob is not None:
            feas += 1
            total += ob
            if sett == "set1":
                s1 += ob
            else:
                s2 += ob
            print(f"  [{sett}] {nm:9s} obj={ob:>14,.0f}  z1={r.get('z1')} z2={r.get('z2')} "
                  f"z3={r.get('z3')}  {r.get('wall')}s   [feas {feas}, 누적 {total:,.0f}]", flush=True)
        else:
            minus1 += 1
            print(f"  [{sett}] {nm:9s} INFEASIBLE stage={r.get('stage')}  {r.get('wall')}s  ⚠ -1위험",
                  flush=True)
        rows.append({"nm": nm, "set": sett, "obj": ob,
                     **{k: r.get(k) for k in ("z1", "z2", "z3", "wall", "stage")}})
        json.dump({"tl": tl, "mode": "bestof_global1", "total": total, "set1": s1, "set2": s2,
                   "feasible": feas, "minus1": minus1, "n": len(names), "maxwall": maxwall,
                   "rows": rows},
                  open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n==== NEW best-of(g1) TOTAL ({feas}/{len(names)} feasible) ====", flush=True)
    print(f"  총 obj = {total:,.0f}   (set1={s1:,.0f}  set2={s2:,.0f})", flush=True)
    print(f"  INFEAS/-1 = {minus1}   maxwall = {maxwall:.0f}s", flush=True)
    print(f"  -- 비교 기준 --", flush=True)
    print(f"  v2-단독 g0(기록): 239,266,653  (set1 13,955,294 / set2 225,311,359)", flush=True)
    print(f"  배포 best-of set2 ~= 225,311,359 (v2 가 set2 best-of 승)", flush=True)
    print(f"  저장: {outp}", flush=True)


if __name__ == "__main__":
    main()
