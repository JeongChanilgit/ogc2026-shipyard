"""
static_all_bays.py — 정적 밀도 방법(AABB vs 폴리곤 BL)을 *실제 인스턴스 전체*에 적용.

지금까지는 prob_29 의 혼잡 bay 0 (선호 116블록) 하나만 봤다 = 극단 케이스.
실제 상황 = 인스턴스의 *모든 베이*, 각 베이마다 부하가 다름. 여기선:
  - 각 블록을 최선호 베이(argmax bay_preferences)에 배정 ("모두 선호 베이로" 자연 배정)
  - 베이마다 AABB BL vs 폴리곤 BL (area 순서) 정적 max-fit
  - 개수(of N) / 면적포화 / 부피포화 / 시간 보고 + 베이별 비교

실행: <env-python> static_all_bays.py [instance_path]  (기본 prob_29)
주의: 정적 = "한 순간 최대 몇 개" = 밀도 측정. Z1(지각)은 temporal 트랙에서.
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from gridmap import build_shape, AABBGrid, BayGrid  # noqa: E402
from blf import bottom_left_fill  # noqa: E402

SCALE = 2


def pack_bay(blocks, subset, W, H):
    """subset 블록을 (W,H) 베이에 AABB / 폴리곤 BL 정적 max-fit. 두 결과 dict."""
    shapes = {}
    ml = 1
    for i in subset:
        shs = [build_shape(i, blocks[i], o, SCALE) for o in range(len(blocks[i]["shape"]))]
        shapes[i] = shs
        ml = max(ml, max(s.n_layers for s in shs))
    order = sorted(subset, key=lambda i: -shapes[i][0].footprint_area)
    out = {}
    for tag, GridCls, args, kw in [("AABB", AABBGrid, (W, H, ml), {}),
                                   ("POLY", BayGrid, (W, H, ml, SCALE), {"exact": True})]:
        g = GridCls(*args, **kw)
        t0 = time.time()
        placed, _ = bottom_left_fill(g, shapes, order, entry_mode=False)
        tot_f = tot_v = 0.0
        for (bid, x, y, oi) in placed:
            sh = next(s for s in shapes[bid] if s.orient_idx == oi)
            tot_f += sh.footprint_area
            tot_v += sh.volume
        out[tag] = {"fit": len(placed), "area": tot_f / (W * H),
                    "vol": tot_v / (W * H * ml), "time": time.time() - t0, "ml": ml}
    return out


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        THIS, "..", "instances", "train", "prob_29.json")
    data = json.load(open(inst, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    m = len(bays)
    pref = [max(range(m), key=lambda j: blocks[i]["bay_preferences"][j])
            for i in range(len(blocks))]

    name = os.path.basename(inst)
    print(f"== 정적 밀도 (모든 베이) : {name}  —  {len(blocks)} blocks, {m} bays ==\n")
    print(f"{'베이':<5}{'크기':>9}{'선호블록':>8}{'  방식':<7}"
          f"{'배치/of':>10}{'면적%':>8}{'부피%':>8}{'시간':>7}")
    print("-" * 70)

    tot = {"AABB": [0, 0], "POLY": [0, 0]}   # [fit, subset]
    for j in range(m):
        subset = [i for i in range(len(blocks)) if pref[i] == j]
        W, H = bays[j]["width"], bays[j]["height"]
        size = f"{W}x{H}"
        if not subset:
            print(f"{j:<5}{size:>9}{0:>8}   (선호 블록 없음)")
            continue
        res = pack_bay(blocks, subset, W, H)
        for k, tag in enumerate(("AABB", "POLY")):
            r = res[tag]
            head = f"{j:<5}{size:>9}{len(subset):>8}" if k == 0 else f"{'':<5}{'':>9}{'':>8}"
            print(f"{head}  {tag:<5}{r['fit']:>7}/{len(subset):<3}"
                  f"{r['area']*100:>7.1f}%{r['vol']*100:>7.1f}%{r['time']:>7.1f}")
            tot[tag][0] += r["fit"]
            tot[tag][1] += len(subset)
    print("-" * 70)
    for tag in ("AABB", "POLY"):
        f_, n_ = tot[tag]
        print(f"{'합계':<22}  {tag:<5}{f_:>7}/{n_:<3}"
              f"  (동시 배치 가능 블록 / 선호 합)")
    print("\n주: '배치/of' = 그 베이 선호 블록 중 한 순간에 동시에 들어가는 수 (정적 max-fit).")
    print("   부피% = 전 레이어 면적합 / (W·H·max_layer). Z1 은 temporal 트랙.")


if __name__ == "__main__":
    main()
