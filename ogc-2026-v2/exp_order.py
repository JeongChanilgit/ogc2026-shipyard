"""exp_order.py — construction 레버: 전역 Pass B 배치 순서(OGC_ORDER) 스윕 A/B.

EDD 대신 slack/area/release/areaXdue 가 z1 을 줄이나. 단일 best 순서를 찾으면 채택(best-of 아님).
실행: <env-python> exp_order.py [prob ...]
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
ORDERS = ["edd", "slack", "area", "release", "areaXdue"]


def main():
    names = sys.argv[1:] or ["prob_26", "prob_33", "prob_27"]
    print(f"== 배치순서 스윕 @TL120 ==  {names}", flush=True)
    rows = {o: {} for o in ORDERS}
    base = {}
    for o in ORDERS:
        os.environ["OGC_ORDER"] = o
        tot, z1t = 0.0, 0
        for nm in names:
            data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
            path = os.path.join(TRAIN, nm + ".json")
            t0 = time.time()
            res, _d, _ok, _t = ug.unified(data, 120.0, path)
            obj = res.get("objective")
            rows[o][nm] = obj
            if obj is not None:
                tot += obj
                z1t += res.get("obj1") or 0
            tag = "(base)" if o == "edd" else (f"{(base.get(nm,obj)-obj)/base.get(nm,obj)*100:+.1f}%"
                                               if base.get(nm) else "")
            print(f"  {o:9s} {nm:9s} obj={obj:>14,.0f}  z1={res.get('obj1')}  "
                  f"{time.time()-t0:.0f}s  {tag}", flush=True)
        if o == "edd":
            base = dict(rows["edd"])
            base_tot = tot
        d = base_tot - tot if o != "edd" else 0
        print(f"  --- {o}: 총={tot:,.0f} z1합={z1t}"
              f"{'' if o=='edd' else f'  Δ {d:+,.0f} ({d/base_tot*100:+.2f}%)'} ---\n", flush=True)
    print("==== 요약 ====", flush=True)
    for o in ORDERS:
        tot = sum(v for v in rows[o].values() if v is not None)
        print(f"  {o:9s} 총={tot:,.0f}", flush=True)


if __name__ == "__main__":
    main()
