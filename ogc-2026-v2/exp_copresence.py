"""exp_copresence.py — E1 실험: anticipatory 공존 페널티(OGC_COPRESENCE) 스윕 A/B.

전역 marginal 에 "이 베이에 시간창 겹치는 기존 블록 수 × CP_W × w1" 추가가 z1 을 줄이나.
z1-heavy 인스턴스에 CP_W ∈ {0, 0.1, 0.3, 1.0} 쓸어 총 obj 비교. CP_W=0 = 현 production.
실행: <env-python> exp_copresence.py [prob ...]
"""
from __future__ import annotations

import os
import sys
import json
import time

os.environ["OGC_FIT"] = "1"
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ["OGC_GLOBAL"] = "1"

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
CPWS = [0.0, 0.1, 0.3, 1.0]


def main():
    names = sys.argv[1:] or ["prob_26", "prob_27", "prob_33", "prob_38"]
    print(f"== E1 공존페널티 스윕 @TL120 ==  인스턴스 {names}", flush=True)
    base = {}
    rows = {cp: {} for cp in CPWS}
    for cp in CPWS:
        os.environ["OGC_COPRESENCE"] = str(cp)
        tot, z1tot = 0.0, 0
        for nm in names:
            data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
            path = os.path.join(TRAIN, nm + ".json")
            t0 = time.time()
            res, _d, _ok, _t = ug.unified(data, 120.0, path)
            obj = res.get("objective")
            rows[cp][nm] = (obj, res.get("obj1"), time.time() - t0)
            if obj is not None:
                tot += obj
                z1tot += res.get("obj1") or 0
            tag = "(base)" if cp == 0 else (f"{(base.get(nm,obj)-obj)/base.get(nm,obj)*100:+.1f}%"
                                            if base.get(nm) else "")
            print(f"  CP={cp:<4} {nm:9s} obj={obj:>14,.0f}  z1={res.get('obj1')}  "
                  f"{time.time()-t0:.0f}s  {tag}", flush=True)
        if cp == 0:
            base = {nm: rows[0][nm][0] for nm in names}
            base_tot = tot
        d = base_tot - tot if cp != 0 else 0
        print(f"  --- CP={cp}: 총 obj={tot:,.0f}  z1합={z1tot}"
              f"{'' if cp==0 else f'  Δ vs base {d:+,.0f} ({d/base_tot*100:+.2f}%)'} ---\n", flush=True)
    print("==== 요약 (총 obj) ====", flush=True)
    for cp in CPWS:
        tot = sum(rows[cp][nm][0] for nm in names if rows[cp][nm][0] is not None)
        print(f"  CP={cp:<4} 총={tot:,.0f}", flush=True)


if __name__ == "__main__":
    main()
