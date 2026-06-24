"""
density_experiment.py — "겹침 최대화" 패커 측정 + 4코어 포트폴리오.

비교:
  AABB (옛 방식, bottom-left)         : 밀도 천장 하한
  POLY bl       (벡터화)              : 폴리곤 허용 + bottom-left
  POLY overlap  (area/due/height 순서): 폴리곤 + *겹침 최대화*  ← 사용자 아이디어
  portfolio best                       : 4코어 병렬 best-of

각 구성의 count(동시배치)/util(면적활용)/time(속도) 을 표로. best 는 shapely 정확검증 +
viz 출력. 속도(time)로 "contact-area 레버 부활 가능성"(옛날 net-neg) 판정.

실행: <env-python> density_experiment.py
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from gridmap import build_shape, AABBGrid  # noqa: E402
from blf import bottom_left_fill  # noqa: E402
from density_pack import pack_run, pack_portfolio, _argmax  # noqa: E402

try:
    from viz import write_viz
except Exception:
    write_viz = None

INST = os.path.join(THIS, "..", "instances", "train", "prob_29.json")
SCALE = 2
OUT = os.path.join(THIS, "out")


def aabb_baseline(inst, bay_id):
    """옛 AABB bottom-left (참조 하한)."""
    data = json.load(open(inst, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    pref = [_argmax(b["bay_preferences"]) for b in blocks]
    if bay_id is None:
        bay_id = _argmax([pref.count(j) for j in range(len(bays))])
    subset = [i for i in range(len(blocks)) if pref[i] == bay_id]
    W, H = bays[bay_id]["width"], bays[bay_id]["height"]
    shapes = {}
    ml = 1
    for i in subset:
        shs = [build_shape(i, blocks[i], o, SCALE) for o in range(len(blocks[i]["shape"]))]
        shapes[i] = shs
        ml = max(ml, max(s.n_layers for s in shs))
    order = sorted(subset, key=lambda i: -shapes[i][0].footprint_area)
    grid = AABBGrid(W, H, ml)
    t0 = time.time()
    placed, _ = bottom_left_fill(grid, shapes, order, entry_mode=False)
    tot_floor = tot_vol = 0.0
    for (bid, x, y, oi) in placed:
        sh = next(s for s in shapes[bid] if s.orient_idx == oi)
        tot_floor += sh.footprint_area
        tot_vol += sh.volume
    return {"scorer": "AABB", "order": "area", "count": len(placed),
            "subset": len(subset), "util": tot_floor / (W * H),
            "vol_util": tot_vol / (W * H * ml),
            "time": time.time() - t0, "bay": bay_id, "W": W, "H": H, "max_layer": ml}


def verify_overlap(inst, best):
    """best.placements 의 shapely 같은-층 무겹침 확인."""
    from shapely.affinity import translate
    data = json.load(open(inst, encoding="utf-8"))
    blocks = data["blocks"]
    worlds = []
    for (bid, x, y, oi) in best["placements"]:
        sh = build_shape(bid, blocks[bid], oi, SCALE)
        worlds.append({l: translate(sh.layers[l].poly, xoff=x, yoff=y)
                       for l in range(sh.n_layers)})
    mx = 0.0
    for a in range(len(worlds)):
        for b in range(a + 1, len(worlds)):
            for l in worlds[a].keys() & worlds[b].keys():
                mx = max(mx, worlds[a][l].intersection(worlds[b][l]).area)
    return mx


def make_trace(inst, best):
    data = json.load(open(inst, encoding="utf-8"))
    blocks = data["blocks"]
    tr = {"instance": "prob_29",
          "bay": {"id": best["bay"], "width": best["W"], "height": best["H"],
                  "max_layer": best["max_layer"]},
          "blocks": {}, "events": [],
          "stats": {k: best[k] for k in ("scorer", "order", "count", "subset", "util", "time")}}
    for t, (bid, x, y, oi) in enumerate(best["placements"]):
        lr = blocks[bid]["shape"][oi]["layers"]
        tr["blocks"][str(bid)] = {
            "orient_idx": oi,
            "layers": [[[float(px), float(py)] for px, py in lyr] for lyr in lr],
            "release": blocks[bid].get("release_time", 0),
            "due": blocks[bid].get("due_date", 0),
            "proc": blocks[bid].get("processing_time", 0)}
        tr["events"].append({"t": t, "type": "ENTRY", "block_id": bid, "x": x, "y": y})
    return tr


def main():
    os.makedirs(OUT, exist_ok=True)
    bay_id = None   # 자동 = 혼잡 베이

    print("== 겹침-최대화 패커 측정 (prob_29 혼잡 베이) ==\n")
    base = aabb_baseline(INST, bay_id)
    bay_id = base["bay"]
    print(f"혼잡 베이 = bay {bay_id} ({base['W']}x{base['H']}), 선호 블록 {base['subset']}\n")

    configs = [
        {"scorer": "bl", "order_key": "area"},
        {"scorer": "overlap", "order_key": "area"},
        {"scorer": "vol", "order_key": "area"},
        {"scorer": "vol", "order_key": "due"},
        {"scorer": "vol", "order_key": "height"},
    ]
    t0 = time.time()
    best, results = pack_portfolio(INST, bay_id, SCALE, configs, workers=4)
    wall = time.time() - t0

    print(f"{'구성':<20}{'배치':>5}{'면적%':>8}{'부피%':>8}{'시간':>7}")
    print("-" * 50)
    print(f"{'AABB/area (옛)':<20}{base['count']:>5}{base['util']*100:>7.1f}%"
          f"{base['vol_util']*100:>7.1f}%{base['time']:>7.1f}")
    for r in results:
        tag = f"{r['scorer']}/{r['order']}"
        mark = "  <- best(부피)" if r is best else ""
        print(f"{tag:<20}{r['count']:>5}{r['util']*100:>7.1f}%"
              f"{r['vol_util']*100:>7.1f}%{r['time']:>7.1f}{mark}")
    print("-" * 50)
    print(f"포트폴리오 wall(4코어 병렬) = {wall:.1f}s\n")

    print(f"=> best 부피({best['scorer']}/{best['order']}) = {best['vol_util']*100:.1f}% "
          f"(블록 {best['count']}개) vs AABB 부피 {base['vol_util']*100:.1f}% "
          f"({base['count']}개) = +{(best['vol_util']-base['vol_util'])*100:.1f}%p")

    mx = verify_overlap(INST, best)
    print(f"shapely 정확검증: 최대 같은-층 겹침 = {mx:.5f}  "
          f"({'OK' if mx < 1e-6 else 'WARN'})")

    if write_viz is not None:
        out = os.path.join(OUT, f"prob_29_bay{bay_id}_{best['scorer']}.html")
        write_viz(make_trace(INST, best), out)
        print(f"viz: {out}")

    print("\n== 끝 ==")


if __name__ == "__main__":
    main()
