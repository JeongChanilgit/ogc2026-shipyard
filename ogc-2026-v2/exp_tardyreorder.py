"""exp_tardyreorder.py — 사용자 정밀 아이디어: tardy-doomed 블록들끼리만 small-first.

pass1: blend(R+0.5P)로 배치 → 어느 블록이 tardy(exit>due)인지 예측.
reorder: base blend 순서에서 *tardy 블록들의 위치*만 area-small 순으로 채움(on-time 불변).
pass2: 그 custom 순서로 재배치. on-time은 exit-imminence, tardy끼리는 작은거 먼저.
실행: <env-python> exp_tardyreorder.py [prob ...]
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
os.environ["OGC_ORDER_ALPHA"] = "0.5"

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import unified_greedy as ug   # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")


def bbox_area(b):
    xs = [p[0] for ly in b["shape"][0]["layers"] for p in ly]
    ys = [p[1] for ly in b["shape"][0]["layers"] for p in ly]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def blend_order(blocks, N):
    return sorted(range(N), key=lambda i: (blocks[i].get("release_time", 0)
                  + 0.5 * blocks[i]["processing_time"], blocks[i]["due_date"]))


def tardy_set(sol, blocks):
    ex = {}
    for ts, ops in sol["operations"].items():
        for o in ops:
            if o.get("type") == "EXIT":
                ex[int(o["block_id"])] = int(ts)
    return {b for b, x in ex.items() if x > blocks[b]["due_date"]}


def main():
    names = sys.argv[1:] or ["prob_27", "prob_33", "prob_38", "prob_22"]
    print("== 2-pass tardy-reorder (tardy끼리만 small-first) @TL120 ==", flush=True)
    tb, ta = 0.0, 0.0
    for nm in names:
        data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
        path = os.path.join(TRAIN, nm + ".json")
        blocks = data["blocks"]
        N = len(blocks)
        # pass 1: blend
        os.environ["OGC_ORDER"] = "blend"
        ug._CUSTOM_ORDER = None
        res1, _d, _o, _t = ug.unified(data, 120.0, path)
        obj1 = res1.get("objective")
        T = tardy_set(res1.get("_solution", {"operations": {}}), blocks)
        # reorder: tardy 위치에 area-small 채움
        base = blend_order(blocks, N)
        area = [bbox_area(b) for b in blocks]
        pos = [k for k, i in enumerate(base) if i in T]
        tsort = sorted((base[k] for k in pos), key=lambda i: area[i])
        new = list(base)
        for k, i in zip(pos, tsort):
            new[k] = i
        # pass 2: custom
        os.environ["OGC_ORDER"] = "custom"
        ug._CUSTOM_ORDER = new
        res2, _d, _o, _t = ug.unified(data, 120.0, path)
        obj2 = res2.get("objective")
        ug._CUSTOM_ORDER = None
        d = (obj1 - obj2) if (obj1 and obj2) else 0
        if obj1 and obj2:
            tb += obj1; ta += obj2
        print(f"  {nm:9s} tardy={len(T):3d}  pass1(blend)={obj1:>14,.0f} (z1={res1.get('obj1')})  "
              f"pass2(tardy-small)={obj2:>14,.0f} (z1={res2.get('obj1')})  "
              f"Δ {d:+,.0f} ({100*d/obj1:+.1f}%)" if obj1 else f"  {nm}: INFEAS", flush=True)
    if tb:
        print(f"\n  총: pass1={tb:,.0f}  pass2={ta:,.0f}  Δ {tb-ta:+,.0f} ({100*(tb-ta)/tb:+.2f}%)", flush=True)


if __name__ == "__main__":
    main()
