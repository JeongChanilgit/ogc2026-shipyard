"""
pack_compare_3d.py — 같은 베이·같은 블록집합을 원래 fastfloor 패커 vs v2 패커로
각각 패킹 → 3D 두 개. 원래가 폴리곤 오목부를 살리는지 vs v2 비교.

실행: <env-python> pack_compare_3d.py prob_29 1   (인스턴스, bay_idx)
"""
from __future__ import annotations

import json
import os
import sys
import time

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))

import utils  # noqa: E402
import fastfloor  # noqa: E402
from assign_search import build_set, SCALE  # noqa: E402
from temporal_pack import simulate, seed_order  # noqa: E402
from viz import write_viz  # noqa: E402

from shapely.geometry import Polygon  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
OUT = os.path.join(THIS, "out")


def interlock_metrics(blocks, layout):
    """동시공존 쌍 중: bbox 겹침 / 그 중 폴리곤 무충돌(=오목부 interlock) / 폴리곤 충돌."""
    items = []
    for bid, rec in layout.items():
        oi, x, y = rec["orient_idx"], rec["x"], rec["y"]
        wp, minx, miny, maxx, maxy = {}, 1e9, 1e9, -1e9, -1e9
        for l, verts in enumerate(blocks[bid]["shape"][oi]["layers"]):
            poly = Polygon([(px + x, py + y) for px, py in verts])
            if not poly.is_valid:
                poly = poly.buffer(0)
            wp[l] = poly
            b = poly.bounds
            minx, miny = min(minx, b[0]), min(miny, b[1])
            maxx, maxy = max(maxx, b[2]), max(maxy, b[3])
        items.append({"wp": wp, "bbox": (minx, miny, maxx, maxy),
                      "en": rec["entry_time"], "ex": rec["exit_time"]})
    co = bbox_ov = interlock = collide = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            A, B = items[i], items[j]
            if not (A["en"] < B["ex"] and B["en"] < A["ex"]):
                continue
            co += 1
            ax0, ay0, ax1, ay1 = A["bbox"]
            bx0, by0, bx1, by1 = B["bbox"]
            if min(ax1, bx1) - max(ax0, bx0) > 1e-6 and min(ay1, by1) - max(ay0, by0) > 1e-6:
                bbox_ov += 1
                col = any(A["wp"][l].intersection(B["wp"][l]).area > 1e-7
                          for l in A["wp"].keys() & B["wp"].keys())
                if col:
                    collide += 1
                else:
                    interlock += 1
    return {"copresent": co, "bbox_overlap": bbox_ov,
            "interlock": interlock, "collide": collide}


def layout_to_trace(blocks, bay_id, W, H, layout, label):
    """layout = {block_id: {x,y,orient_idx,entry_time,exit_time}} → viz trace."""
    ml = 1
    tr = {"instance": label, "bay": {"id": bay_id, "width": W, "height": H, "max_layer": 1},
          "blocks": {}, "events": [], "stats": {"mode": label, "n": len(layout)}}
    for bid, rec in layout.items():
        oi = rec["orient_idx"]
        lr = blocks[bid]["shape"][oi]["layers"]
        ml = max(ml, len(lr))
        tr["blocks"][str(bid)] = {
            "orient_idx": oi,
            "layers": [[[float(px), float(py)] for px, py in ly] for ly in lr],
            "release": blocks[bid].get("release_time", 0),
            "due": blocks[bid].get("due_date", 0),
            "proc": blocks[bid].get("processing_time", 0)}
        en, ex = int(rec["entry_time"]), int(rec["exit_time"])
        tr["events"].append({"t": en, "type": "ENTRY", "block_id": bid,
                             "x": int(round(rec["x"])), "y": int(round(rec["y"]))})
        tr["events"].append({"t": ex, "type": "EXIT", "block_id": bid})
    tr["bay"]["max_layer"] = ml
    tr["events"].sort(key=lambda e: (e["t"], 0 if e["type"] == "EXIT" else 1))
    return tr


def main():
    os.makedirs(OUT, exist_ok=True)
    nm = sys.argv[1] if len(sys.argv) > 1 else "prob_29"
    bay_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    data = json.load(open(os.path.join(TRAIN, nm + ".json"), encoding="utf-8"))
    bays, blocks = data["bays"], data["blocks"]
    m = len(bays)
    W, H = bays[bay_idx]["width"], bays[bay_idx]["height"]
    pref = [max(range(m), key=lambda j: blocks[i]["bay_preferences"][j]) for i in range(len(blocks))]
    ids = [i for i in range(len(blocks)) if pref[i] == bay_idx]
    print(f"== 패킹 3D 비교: {nm} bay {bay_idx} ({W}x{H}), 선호 블록 {len(ids)} ==", flush=True)

    bay = utils.Bay(width=W, height=H)

    # --- 원래 fastfloor 패커 (이 집합이 안 들어가면 줄여가며) ---
    cur = list(ids)
    orig = None
    while cur:
        res = fastfloor._fixed_time_decode(bay, bay_idx, cur, blocks, time.monotonic() + 30)
        layout = res[0] if isinstance(res, tuple) else res
        if layout:
            orig = layout
            break
        cur = cur[:int(len(cur) * 0.85)]   # 15%씩 줄여 packable 집합 찾기
    if orig is None:
        print("  원래 fastfloor: 빈 결과", flush=True)
        return
    print(f"  원래 fastfloor: {len(orig)} blocks 배치", flush=True)
    use_ids = list(orig.keys())            # 동일 집합으로 v2 비교 (공정)

    # --- v2 패커 (같은 use_ids) ---
    sub = build_set(blocks, W, H, use_ids, SCALE)
    placed, _ = simulate(sub, seed_order(sub, "edd"), allow_stack=True)
    v2 = {p["id"]: {"x": p["x"], "y": p["y"], "orient_idx": p["orient"],
                    "entry_time": p["entry"], "exit_time": p["exit"]} for p in placed}
    print(f"  v2 패커: {len(v2)} blocks 배치", flush=True)

    mo = interlock_metrics(blocks, orig)
    mv = interlock_metrics(blocks, {k: v for k, v in v2.items()})
    print(f"\n  {'지표':<28}{'원래 fastfloor':>16}{'v2':>10}", flush=True)
    print(f"  {'동시공존 쌍':<26}{mo['copresent']:>16}{mv['copresent']:>10}", flush=True)
    print(f"  {'bbox 겹침 쌍':<26}{mo['bbox_overlap']:>16}{mv['bbox_overlap']:>10}", flush=True)
    print(f"  {'└ 오목부 interlock(폴리곤 무충돌)':<22}{mo['interlock']:>16}{mv['interlock']:>10}", flush=True)
    print(f"  {'폴리곤 충돌(있으면 버그)':<24}{mo['collide']:>16}{mv['collide']:>10}", flush=True)
    print(f"\n  => 원래가 bbox 겹침 허용+폴리곤 interlock {mo['interlock']}쌍 "
          f"=> {'폴리곤-aware (AABB 아님)' if mo['interlock'] > 0 else '사실상 bbox 따로(AABB적)'}", flush=True)

    p1 = os.path.join(OUT, f"pk_{nm}_bay{bay_idx}_ORIGINAL_fastfloor.html")
    p2 = os.path.join(OUT, f"pk_{nm}_bay{bay_idx}_V2.html")
    write_viz(layout_to_trace(blocks, bay_idx, W, H, orig, f"원래 fastfloor {nm} bay{bay_idx}"), p1)
    write_viz(layout_to_trace(blocks, bay_idx, W, H, v2, f"v2 패커 {nm} bay{bay_idx}"), p2)
    print(f"  3D 원래: {p1}", flush=True)
    print(f"  3D v2  : {p2}", flush=True)


if __name__ == "__main__":
    main()
