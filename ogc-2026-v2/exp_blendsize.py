"""exp_blendsize.py — 사용자 아이디어: 큰 블록 나중에 (R+α·P+γ·area) γ 스윕.

혼잡(Z1 터짐)에선 작은 블록 먼저 채워 tardy↓, 큰 블록 deferred. γ=0=blend α0.5(base).
실행: <env-python> exp_blendsize.py [prob ...]
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
os.environ["OGC_ORDER"] = "blendsize"
os.environ["OGC_ORDER_ALPHA"] = "0.5"

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
GAMMAS = ["0", "0.1", "0.3", "1.0"]


def main():
    names = sys.argv[1:] or ["prob_27", "prob_33", "prob_22"]
    print(f"== blendsize γ 스윕 (R+0.5P+γ·area) @TL120 ==  {names}", flush=True)
    rows = {g: {} for g in GAMMAS}
    base = {}
    for g in GAMMAS:
        os.environ["OGC_ORDER_GAMMA"] = g
        tot = 0.0
        for nm in names:
            data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
            path = os.path.join(TRAIN, nm + ".json")
            res, _d, _ok, _t = ug.unified(data, 120.0, path)
            obj = res.get("objective")
            rows[g][nm] = obj
            if obj is not None:
                tot += obj
            tag = "(base=blend)" if g == "0" else (f"{(base.get(nm,obj)-obj)/base.get(nm,obj)*100:+.1f}%"
                                                   if base.get(nm) else "")
            print(f"  γ={g:<4} {nm:9s} obj={obj:>14,.0f}  z1={res.get('obj1')}  {tag}", flush=True)
        if g == "0":
            base = dict(rows["0"]); base_tot = tot
        d = base_tot - tot if g != "0" else 0
        print(f"  --- γ={g}: 총={tot:,.0f}{'' if g=='0' else f'  Δ {d:+,.0f} ({d/base_tot*100:+.2f}%)'} ---\n",
              flush=True)
    print("==== 요약 (낮을수록 좋음) ====", flush=True)
    best = None
    for g in GAMMAS:
        tot = sum(v for v in rows[g].values() if v is not None)
        if best is None or tot < best[1]:
            best = (g, tot)
        print(f"  γ={g:<4} 총={tot:,.0f}", flush=True)
    print(f"  → best γ={best[0]}", flush=True)


if __name__ == "__main__":
    main()
