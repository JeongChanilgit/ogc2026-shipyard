"""
show_three.py — 세 방식의 3D 뷰 비교 생성.

  1) AABB        : 옛 바운딩박스 no-overlap (정적 max-fit)
  2) POLY static : 폴리곤 오목부 interlock (정적 max-fit)  ← 직전거
  3) temporal    : 시간축 패킹-스케줄러 (진입/퇴출, overhang 스택 + exit가드)  ← 지금거

각각 out/three_*.html (viz.py 3D 뷰어) 생성. 1·2 는 정적(동시 배치, 진입만), 3 은
116블록 전부를 시간에 걸쳐 흘려보냄(진입+퇴출 애니메이션). temporal 은 내부검증
(공존 무겹침 + 크레인 LIFO) + 실제 Z1(구조적으로 0 아님) 보고.

실행: <env-python> show_three.py
"""
from __future__ import annotations

import json
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from gridmap import build_shape, AABBGrid, BayGrid  # noqa: E402
from blf import bottom_left_fill  # noqa: E402
from temporal_pack import build_subset, simulate, seed_order  # noqa: E402
from temporal_experiment import selfcheck  # noqa: E402
from viz import write_viz  # noqa: E402

INST = os.path.join(THIS, "..", "instances", "train", "prob_29.json")
SCALE = 2
OUT = os.path.join(THIS, "out")


def _layers_raw(blocks, bid, oi):
    return [[[float(px), float(py)] for px, py in lyr]
            for lyr in blocks[bid]["shape"][oi]["layers"]]


def static_trace(blocks, bay_id, W, H, ml, placements, label, stats):
    """정적 배치 → 진입만(t=0,1,2,...), 퇴출 없음 (점진 채움 애니메이션)."""
    tr = {"instance": "prob_29",
          "bay": {"id": bay_id, "width": W, "height": H, "max_layer": ml},
          "blocks": {}, "events": [], "stats": stats}
    for t, (bid, x, y, oi) in enumerate(placements):
        tr["blocks"][str(bid)] = {"orient_idx": oi, "layers": _layers_raw(blocks, bid, oi),
                                  "release": blocks[bid].get("release_time", 0),
                                  "due": blocks[bid].get("due_date", 0),
                                  "proc": blocks[bid].get("processing_time", 0)}
        tr["events"].append({"t": t, "type": "ENTRY", "block_id": bid, "x": x, "y": y})
    return tr


def temporal_trace(blocks, bay_id, W, H, ml, placed, stats):
    tr = {"instance": "prob_29",
          "bay": {"id": bay_id, "width": W, "height": H, "max_layer": ml},
          "blocks": {}, "events": [], "stats": stats}
    for (bid, x, y, oi, en, ex) in placed:
        tr["blocks"][str(bid)] = {"orient_idx": oi, "layers": _layers_raw(blocks, bid, oi),
                                  "release": blocks[bid].get("release_time", 0),
                                  "due": blocks[bid].get("due_date", 0),
                                  "proc": blocks[bid].get("processing_time", 0)}
        tr["events"].append({"t": int(en), "type": "ENTRY", "block_id": bid, "x": x, "y": y})
        tr["events"].append({"t": int(ex), "type": "EXIT", "block_id": bid})
    tr["events"].sort(key=lambda e: (e["t"], 0 if e["type"] == "EXIT" else 1))
    return tr


def main():
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(INST, encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    m = len(bays)
    pref = [max(range(m), key=lambda j: blocks[i]["bay_preferences"][j]) for i in range(len(blocks))]
    bay_id = max(range(m), key=lambda j: pref.count(j))
    subset = [i for i in range(len(blocks)) if pref[i] == bay_id]
    W, H = bays[bay_id]["width"], bays[bay_id]["height"]

    shapes = {}
    ml = 1
    for i in subset:
        shapes[i] = [build_shape(i, blocks[i], o, SCALE) for o in range(len(blocks[i]["shape"]))]
        ml = max(ml, max(s.n_layers for s in shapes[i]))
    order_area = sorted(subset, key=lambda i: -shapes[i][0].footprint_area)

    print(f"== 3-way 비교 (prob_29 bay {bay_id} {W}x{H}, {len(subset)} blocks) ==\n")
    outputs = []

    # 1) AABB
    g = AABBGrid(W, H, ml)
    pa, _ = bottom_left_fill(g, shapes, order_area, entry_mode=False)
    tr = static_trace(blocks, bay_id, W, H, ml, pa,
                      "AABB (옛 바운딩박스, 정적 max-fit)",
                      {"mode": "AABB", "fit": len(pa), "of": len(subset)})
    p = os.path.join(OUT, "three_1_aabb.html"); write_viz(tr, p); outputs.append(p)
    print(f"1) AABB        : {len(pa)}/{len(subset)} 동시 배치  -> {os.path.basename(p)}")

    # 2) POLY static
    g = BayGrid(W, H, ml, SCALE, exact=True)
    pp, _ = bottom_left_fill(g, shapes, order_area, entry_mode=False)
    tr = static_trace(blocks, bay_id, W, H, ml, pp,
                      "POLY static (폴리곤 오목부 interlock, 정적 max-fit)",
                      {"mode": "POLY-static", "fit": len(pp), "of": len(subset)})
    p = os.path.join(OUT, "three_2_poly.html"); write_viz(tr, p); outputs.append(p)
    print(f"2) POLY static : {len(pp)}/{len(subset)} 동시 배치  -> {os.path.basename(p)}")

    # 3) temporal
    sub = build_subset(INST, bay_id, SCALE)
    placed, z1 = simulate(sub, seed_order(sub, "area"), allow_stack=True)
    pl = [(p_["id"], p_["x"], p_["y"], p_["orient"], p_["entry"], p_["exit"]) for p_ in placed]
    ov, crane = selfcheck(sub, pl)
    feas = "FEASIBLE" if (ov < 1e-6 and crane == 0) else f"INFEASIBLE(ov={ov:.3f},crane={crane})"
    horizon = max(p_["exit"] for p_ in placed) if placed else 0
    tr = temporal_trace(blocks, bay_id, W, H, ml, pl,
                        {"mode": "temporal", "blocks": len(pl), "Z1": z1,
                         "horizon": horizon, "check": feas})
    p = os.path.join(OUT, "three_3_temporal.html"); write_viz(tr, p); outputs.append(p)
    print(f"3) temporal    : {len(pl)} 블록 시간흐름, Z1={z1}, 검증={feas}  -> {os.path.basename(p)}")

    print("\n생성된 3D 뷰:")
    for p in outputs:
        print("  " + p)
    print("\n== 끝 ==")


if __name__ == "__main__":
    main()
