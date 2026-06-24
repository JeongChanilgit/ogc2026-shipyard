"""
pack_experiment.py — "그림판 논쟁" 을 수치로 결판내는 실험.

질문: prob_29 블록들이 실제로 (a) 오목 footprint, (b) layer-1 overhang 을 갖나?
      그래서 AABB no-overlap 대신 폴리곤+레이어 기하를 살리면 혼잡 베이에
      블록이 몇 개 더 동시에 들어가나? (= 패킹 밀도 천장 ROI)

단계:
  1) 형상 진단 — 오목도(layer0 area / bbox area), overhang(layer1 ⊄ layer0) 비율.
  2) 혼잡 베이 선정 — 가장 많은 블록이 선호(argmax bay_preferences)하는 베이.
  3) max-fit BLF — AABBGrid vs BayGrid(폴리곤), 같은 order. 들어간 수 + 면적활용 비교.
  4) shapely 정확 교차검증 — 폴리곤 배치가 레이어별로 진짜 안 겹치나.
  5) viz 트레이스 출력 — out/prob_29_bay{j}.html (Front=x-z 로 솔기 눈으로 확인).

실행: <env-python> pack_experiment.py   (numpy + shapely 필요)
검증의 진실은 ../src/utils.py — 여기 결과는 밀도 천장의 방향성 측정용.
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import numpy as np  # noqa: E402

from gridmap import build_shape, BayGrid, AABBGrid  # noqa: E402
from blf import bottom_left_fill  # noqa: E402

try:
    from viz import write_viz
except Exception:
    write_viz = None

INST_PATH = os.path.join(THIS, "..", "instances", "train", "prob_29.json")
SCALE = 2          # 격자 해상도 (셀/단위)
OUT_DIR = os.path.join(THIS, "out")


def argmax(xs):
    return max(range(len(xs)), key=lambda i: xs[i])


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    data = json.load(open(INST_PATH, encoding="utf-8"))
    bays = data["bays"]
    blocks = data["blocks"]
    n, m = len(blocks), len(bays)
    print(f"== prob_29 : {n} blocks, {m} bays ==")
    for j, b in enumerate(bays):
        print(f"   bay {j}: {b['width']} x {b['height']}  area={b['width']*b['height']}")

    # ---- 1) 형상 진단 (orient 0 기준; 오목도/overhang 은 회전 불변) ----
    print("\n-- 1) 형상 진단 --")
    n_concave = n_overhang = n_twolayer = 0
    conc_ratios = []
    t0 = time.time()
    for i, blk in enumerate(blocks):
        sh = build_shape(i, blk, 0, scale=SCALE)
        l0 = sh.layers[0]
        bbox_area = max(1e-9, (l0.poly.bounds[2] - l0.poly.bounds[0]) *
                        (l0.poly.bounds[3] - l0.poly.bounds[1]))
        ratio = l0.area / bbox_area
        conc_ratios.append(ratio)
        if ratio < 0.97:
            n_concave += 1
        if sh.n_layers >= 2:
            n_twolayer += 1
            # overhang: layer1 footprint 이 layer0 안에 완전히 들어가지 않으면 캔틸레버
            if not sh.layers[1].poly.buffer(-1e-6).within(l0.poly):
                n_overhang += 1
    conc_ratios = np.array(conc_ratios)
    print(f"   오목 footprint(area/bbox<0.97): {n_concave}/{n}  "
          f"(중앙값 비율 {np.median(conc_ratios):.3f}, 최소 {conc_ratios.min():.3f})")
    print(f"   2-layer 블록: {n_twolayer}/{n};  그 중 overhang(layer1 not-in layer0): {n_overhang}")
    print(f"   => 수평 오목부 interlock 가능={'YES' if n_concave else 'no'}, "
          f"수직 overhang interlock 가능={'YES' if n_overhang else 'no'}  "
          f"({time.time()-t0:.1f}s)")

    # ---- 2) 혼잡 베이 ----
    pref_bay = [argmax(blk["bay_preferences"]) for blk in blocks]
    counts = [pref_bay.count(j) for j in range(m)]
    cbay = argmax(counts)
    subset = [i for i in range(n) if pref_bay[i] == cbay]
    W, H = bays[cbay]["width"], bays[cbay]["height"]
    print(f"\n-- 2) 혼잡 베이 = bay {cbay} ({W}x{H}), 선호 블록 {counts[cbay]}/{n} --")

    # ---- subset 의 모든 방향 BlockShape 준비 ----
    t0 = time.time()
    shapes_by_block = {}
    max_layer = 1
    for i in subset:
        shs = []
        n_or = len(blocks[i]["shape"])
        for o in range(n_or):
            sh = build_shape(i, blocks[i], o, scale=SCALE)
            shs.append(sh)
            max_layer = max(max_layer, sh.n_layers)
        shapes_by_block[i] = shs
    print(f"   {len(subset)} blocks x orients 래스터화 done ({time.time()-t0:.1f}s), "
          f"max_layer={max_layer}")

    # 배치 순서: layer0 면적 큰 것부터 (표준 BLF)
    order = sorted(subset, key=lambda i: -shapes_by_block[i][0].footprint_area)

    # ---- 3) AABB vs 폴리곤 max-fit ----
    print("\n-- 3) max-fit BLF (정적, 같은-층 충돌만) --")
    res = {}
    for tag, GridCls, args, kw in [("AABB", AABBGrid, (W, H, max_layer), {}),
                                   ("POLY", BayGrid, (W, H, max_layer, SCALE),
                                    {"exact": True})]:
        grid = GridCls(*args, **kw)
        t0 = time.time()
        placed, unplaced = bottom_left_fill(grid, shapes_by_block, order, entry_mode=False)
        util = grid.occupied_floor_area()
        dt = time.time() - t0
        res[tag] = (placed, util, dt)
        print(f"   {tag}: {len(placed):3d}/{len(subset)} placed, "
              f"floor-util(layer0 면적합/베이) = {util*100:5.1f}%, {dt:.1f}s")

    a_n = len(res["AABB"][0])
    p_n = len(res["POLY"][0])
    gain = p_n - a_n
    print(f"   => 폴리곤이 AABB 대비 +{gain} 블록 "
          f"(+{(p_n/max(1,a_n)-1)*100:.1f}%), "
          f"면적활용 {res['AABB'][1]*100:.1f}% → {res['POLY'][1]*100:.1f}%")

    # ---- 4) shapely 정확 교차검증 (폴리곤 배치, 레이어별 무겹침) ----
    print("\n-- 4) shapely 정확 교차검증 (POLY 배치) --")
    placed = res["POLY"][0]
    worlds = []   # (bid, layer -> shapely poly@world)
    from shapely.affinity import translate
    for (bid, x, y, oi) in placed:
        sh = next(s for s in shapes_by_block[bid] if s.orient_idx == oi)
        wl = {l: translate(sh.layers[l].poly, xoff=x, yoff=y) for l in range(sh.n_layers)}
        worlds.append((bid, wl))
    max_overlap = 0.0
    n_pairs = 0
    for a in range(len(worlds)):
        _, wa = worlds[a]
        for b in range(a + 1, len(worlds)):
            _, wb = worlds[b]
            for l in set(wa) & set(wb):    # 같은 층만 충돌
                inter = wa[l].intersection(wb[l]).area
                if inter > max_overlap:
                    max_overlap = inter
                n_pairs += 1
    verdict = "OK (무겹침)" if max_overlap < 1e-6 else f"⚠ 최대겹침 {max_overlap:.4f}"
    print(f"   같은-층 쌍 {n_pairs} 검사, {verdict}")

    # ---- 5) viz 트레이스 ----
    if write_viz is not None:
        trace = {
            "instance": "prob_29",
            "bay": {"id": cbay, "width": W, "height": H, "max_layer": max_layer},
            "blocks": {}, "events": [],
            "stats": {
                "congested_bay": cbay, "preferred_blocks": counts[cbay],
                "AABB_fit": a_n, "POLY_fit": p_n, "gain": gain,
                "util_AABB_%": round(res["AABB"][1]*100, 1),
                "util_POLY_%": round(res["POLY"][1]*100, 1),
                "concave_blocks": n_concave, "overhang_blocks": n_overhang,
            },
        }
        for t, (bid, x, y, oi) in enumerate(placed):
            layers_raw = blocks[bid]["shape"][oi]["layers"]
            trace["blocks"][str(bid)] = {
                "orient_idx": oi,
                "layers": [[[float(px), float(py)] for px, py in lyr] for lyr in layers_raw],
                "release": blocks[bid].get("release_time", 0),
                "due": blocks[bid].get("due_date", 0),
                "proc": blocks[bid].get("processing_time", 0),
            }
            trace["events"].append({"t": t, "type": "ENTRY",
                                    "block_id": bid, "x": x, "y": y})
        out = os.path.join(OUT_DIR, f"prob_29_bay{cbay}_poly.html")
        write_viz(trace, out)
        print(f"\n-- 5) viz: {out}")
        print("   (브라우저에서 Front=x-z 프리셋으로 대각선 솔기 확인)")
    else:
        print("\n-- 5) viz 모듈 import 실패 — 스킵 --")

    print("\n== 끝 ==")


if __name__ == "__main__":
    main()
