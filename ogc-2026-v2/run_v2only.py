"""run_v2only.py — 원래솔버 OFF, v2(전역 Pass B)만 *풀 TL* 로 set2 실행 + 저장.

best-of 없음 → v2 가 TL 전부 사용 → CP-SAT 타이밍이 elapsed 뒤 남는 시간(~40s)을 받아
z1 더 깎인다(예산 72s 의 8s 대비). 결과 results/ 에 증분 저장.
비교 기준: g0-단독(전역 off) = out/all40_fit1.json.
실행(env-python 직접): <env-python> run_v2only.py [TL] [prob_X ...]   (기본 120, set2)
"""
from __future__ import annotations

import os
import sys

os.environ["OGC_FIT"] = "1"
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ["OGC_GLOBAL"] = "1"          # 전역 Pass B
os.environ["OGC_TOSS"] = "0"

import json   # noqa: E402
import time   # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
RES = os.path.join(THIS, "results")


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    names = sys.argv[2:] or [f"prob_{i}" for i in range(21, 41)]
    os.makedirs(RES, exist_ok=True)
    outp = os.path.join(RES, f"v2only_global1_tl{int(tl)}.json")
    # g0 비교 기준 로드
    base = {}
    try:
        bj = json.load(open(os.path.join(THIS, "out", "all40_fit1.json"), encoding="utf-8"))
        base = {r["nm"]: r["obj"] for r in bj["rows"]}
    except Exception:
        pass
    print(f"== v2-only(전역, 원래솔버 OFF) 풀TL={tl}s set2 ==  저장→{outp}", flush=True)
    rows, total, feas, minus1, b0tot, maxwall = [], 0.0, 0, 0, 0.0, 0.0
    for nm in names:
        inst = os.path.join(TRAIN, nm + ".json")
        data = json.load(open(inst, encoding="utf-8"))
        t0 = time.time()
        try:
            res, dist, ok, dt = ug.unified(data, tl, inst)
            obj = res.get("objective")
        except Exception as e:
            obj, res = None, {"stage": f"CRASH {type(e).__name__}: {str(e)[:60]}"}
        wall = time.time() - t0
        maxwall = max(maxwall, wall)
        b0 = base.get(nm)
        if obj is not None:
            feas += 1
            total += obj
            over = "  ⚠TL초과" if wall > tl + 2 else ""
            if b0:
                b0tot += b0
                cmp = f"  vs g0={b0:,.0f} ({100*(b0-obj)/b0:+.1f}%)"
            else:
                cmp = ""
            print(f"  {nm:9s} obj={obj:>14,.0f}  z1={res.get('obj1')} z2={res.get('obj2')} "
                  f"z3={res.get('obj3')}  {wall:.0f}s{over}{cmp}", flush=True)
        else:
            minus1 += 1
            print(f"  {nm:9s} INFEAS/CRASH {res.get('stage')}  {wall:.0f}s  ⚠", flush=True)
        rows.append({"nm": nm, "obj": obj, "z1": res.get("obj1"), "z2": res.get("obj2"),
                     "z3": res.get("obj3"), "wall": round(wall, 1), "g0": b0})
        json.dump({"tl": tl, "mode": "v2only_global1", "total": total, "feasible": feas,
                   "minus1": minus1, "maxwall": maxwall, "n": len(names), "rows": rows},
                  open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n==== v2-only(g1) 풀TL TOTAL ({feas}/{len(names)} feasible) ====", flush=True)
    print(f"  총 obj = {total:,.0f}   INFEAS/-1 = {minus1}   maxwall = {maxwall:.0f}s", flush=True)
    if b0tot:
        print(f"  같은 인스턴스 g0-단독 합 = {b0tot:,.0f}  → Δ {b0tot-total:+,.0f} "
              f"({100*(b0tot-total)/b0tot:+.1f}%)", flush=True)
    print(f"  저장: {outp}", flush=True)


if __name__ == "__main__":
    main()
