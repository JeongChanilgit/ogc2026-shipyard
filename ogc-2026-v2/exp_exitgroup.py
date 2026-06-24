"""exp_exitgroup.py — exit-group 베이배정(OGC_EXITGROUP) 스윕. 사용자 아이디어 bay-level.

같은-exit(±TAU) 블록을 같은 베이로 모으면 그룹이 함께 빠져 베이 통째 회전 → z1↓ 가설.
E1 co-presence(겹침 흩기)와 반대. 현 채택 order=exitearly 위에서. EG=0=base.
실행: <env-python> exp_exitgroup.py [prob ...]
"""
from __future__ import annotations

import os
import sys
import json

os.environ["OGC_FIT"] = "1"
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ["OGC_GLOBAL"] = "1"
os.environ["OGC_ORDER"] = "blend"        # 채택 base
os.environ["OGC_ORDER_ALPHA"] = "0.5"

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
EGS = ["0", "0.3", "1", "3"]


def main():
    names = sys.argv[1:] or ["prob_26", "prob_27", "prob_30", "prob_22"]
    print(f"== exit-group 스윕(OGC_EXITGROUP) @TL120, order=exitearly ==  {names}", flush=True)
    rows = {e: {} for e in EGS}
    base = {}
    for e in EGS:
        os.environ["OGC_EXITGROUP"] = e
        tot = 0.0
        for nm in names:
            data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
            path = os.path.join(TRAIN, nm + ".json")
            res, _d, _ok, _t = ug.unified(data, 120.0, path)
            obj = res.get("objective")
            rows[e][nm] = obj
            if obj is not None:
                tot += obj
            tag = "(base)" if e == "0" else (f"{(base.get(nm,obj)-obj)/base.get(nm,obj)*100:+.1f}%"
                                             if base.get(nm) else "")
            print(f"  EG={e:<4} {nm:9s} obj={obj:>14,.0f}  z1={res.get('obj1')}  {tag}", flush=True)
        if e == "0":
            base = dict(rows["0"]); base_tot = tot
        d = base_tot - tot if e != "0" else 0
        print(f"  --- EG={e}: 총={tot:,.0f}{'' if e=='0' else f'  Δ {d:+,.0f} ({d/base_tot*100:+.2f}%)'} ---\n",
              flush=True)
    print("==== 요약 ====", flush=True)
    for e in EGS:
        tot = sum(v for v in rows[e].values() if v is not None)
        print(f"  EG={e:<4} 총={tot:,.0f}", flush=True)


if __name__ == "__main__":
    main()
