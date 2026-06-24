"""exp_alpha.py — 배치순서 R+α·P 블렌드의 α 스윕 (사용자 "둘 다" 아이디어, 원리적).

release(α=0) ↔ exitearly(α=1) 사이 + 그 너머. exitearly가 회귀한 인스턴스(prob_30/32)를
중간/높은 α가 잡으면서 승(prob_26/27/31) 유지하나. 단일 config(best-of 아님).
실행: <env-python> exp_alpha.py [prob ...]
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
os.environ["OGC_ORDER"] = "blend"

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
ALPHAS = ["0", "0.5", "1", "1.5", "2"]


def main():
    names = sys.argv[1:] or ["prob_26", "prob_27", "prob_30", "prob_31", "prob_32"]
    print(f"== α 스윕 (R+α·P) @TL120 ==  {names}", flush=True)
    rows = {a: {} for a in ALPHAS}
    for a in ALPHAS:
        os.environ["OGC_ORDER_ALPHA"] = a
        tot, z1t = 0.0, 0
        for nm in names:
            data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
            path = os.path.join(TRAIN, nm + ".json")
            res, _d, _ok, _t = ug.unified(data, 120.0, path)
            obj = res.get("objective")
            rows[a][nm] = obj
            if obj is not None:
                tot += obj
                z1t += res.get("obj1") or 0
            print(f"  α={a:<4} {nm:9s} obj={obj:>14,.0f}  z1={res.get('obj1')}", flush=True)
        print(f"  --- α={a}: 총={tot:,.0f} z1합={z1t} ---\n", flush=True)
    print("==== 요약 (총 obj, 낮을수록 좋음) ====", flush=True)
    best = None
    for a in ALPHAS:
        tot = sum(v for v in rows[a].values() if v is not None)
        mark = ""
        if best is None or tot < best[1]:
            best = (a, tot)
        print(f"  α={a:<4} 총={tot:,.0f}", flush=True)
    print(f"  → best α={best[0]} (총 {best[1]:,.0f})", flush=True)


if __name__ == "__main__":
    main()
