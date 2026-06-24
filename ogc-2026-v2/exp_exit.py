"""exp_exit.py — 사용자 아이디어: exit-유사 블록 클러스터링(OGC_EXIT_W) 스윕.

후보 contact 점수에 "free-time(셀이 비는 시각)이 내 exit 과 가까운 셀" 보너스 추가.
exit-유사 블록이 붙어 같이 빠지면 연속공간 생성 → z1 감소 가설. EXIT_W=0 = base(edd).
실행: <env-python> exp_exit.py [prob ...]
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
WS = ["0", "2", "5", "15"]


def main():
    names = sys.argv[1:] or ["prob_26", "prob_33", "prob_27"]
    print(f"== exit-클러스터 스윕(OGC_EXIT_W) @TL120 ==  {names}", flush=True)
    rows = {w: {} for w in WS}
    base = {}
    for w in WS:
        os.environ["OGC_EXIT_W"] = w
        tot, z1t = 0.0, 0
        for nm in names:
            data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
            path = os.path.join(TRAIN, nm + ".json")
            t0 = time.time()
            res, _d, _ok, _t = ug.unified(data, 120.0, path)
            obj = res.get("objective")
            rows[w][nm] = obj
            if obj is not None:
                tot += obj
                z1t += res.get("obj1") or 0
            tag = "(base)" if w == "0" else (f"{(base.get(nm,obj)-obj)/base.get(nm,obj)*100:+.1f}%"
                                             if base.get(nm) else "")
            print(f"  W={w:<3} {nm:9s} obj={obj:>14,.0f}  z1={res.get('obj1')}  "
                  f"{time.time()-t0:.0f}s  {tag}", flush=True)
        if w == "0":
            base = dict(rows["0"])
            base_tot = tot
        d = base_tot - tot if w != "0" else 0
        print(f"  --- W={w}: 총={tot:,.0f} z1합={z1t}"
              f"{'' if w=='0' else f'  Δ {d:+,.0f} ({d/base_tot*100:+.2f}%)'} ---\n", flush=True)
    print("==== 요약 ====", flush=True)
    for w in WS:
        tot = sum(v for v in rows[w].values() if v is not None)
        print(f"  W={w:<3} 총={tot:,.0f}", flush=True)


if __name__ == "__main__":
    main()
