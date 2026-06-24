"""
run_original.py — 원래 솔버(../src/myalgorithm.py)를 인스턴스에 돌려 BEFORE 확보.

공식 obj + 혼잡 베이 3D viz. (하이브리드 이식 전후 비교의 BEFORE 쪽)

실행: <env-python> run_original.py 120 prob_21
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)
sys.path.insert(0, os.path.join(THIS, "..", "src"))

import utils  # noqa: E402
import myalgorithm  # noqa: E402  (원래 솔버)
from viz import write_viz  # noqa: E402

TRAIN = os.path.join(THIS, "..", "instances", "train")
OUT = os.path.join(THIS, "out")


def ops_to_trace(data, ops, label, tag):
    """operations dict → 가장 혼잡한 베이의 viz trace."""
    bays, blocks = data["bays"], data["blocks"]
    ent, ext = {}, {}
    for t_str, opl in ops.items():
        for o in opl:
            bid = o["block_id"]
            if o["type"] == "ENTRY":
                ent[bid] = (o["bay_id"], int(round(o.get("x", 0))), int(round(o.get("y", 0))),
                            o.get("orient_idx", 0), int(t_str))
            else:
                ext[bid] = int(t_str)
    bay_cnt = Counter(v[0] for v in ent.values())
    bay = bay_cnt.most_common(1)[0][0]
    W, H = bays[bay]["width"], bays[bay]["height"]
    ml = 1
    tr = {"instance": tag, "bay": {"id": bay, "width": W, "height": H, "max_layer": 1},
          "blocks": {}, "events": [], "stats": {"mode": label, "bay": bay}}
    for bid, (bj, x, y, oi, en) in ent.items():
        if bj != bay:
            continue
        lr = blocks[bid]["shape"][oi]["layers"]
        ml = max(ml, len(lr))
        tr["blocks"][str(bid)] = {
            "orient_idx": oi,
            "layers": [[[float(px), float(py)] for px, py in ly] for ly in lr],
            "release": blocks[bid].get("release_time", 0),
            "due": blocks[bid].get("due_date", 0),
            "proc": blocks[bid].get("processing_time", 0)}
        tr["events"].append({"t": en, "type": "ENTRY", "block_id": bid, "x": x, "y": y})
        if bid in ext:
            tr["events"].append({"t": ext[bid], "type": "EXIT", "block_id": bid})
    tr["bay"]["max_layer"] = ml
    tr["events"].sort(key=lambda e: (e["t"], 0 if e["type"] == "EXIT" else 1))
    tr["stats"]["bay_blocks"] = len(tr["blocks"])
    return tr, bay


def main():
    tl = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    nm = sys.argv[2] if len(sys.argv) > 2 else "prob_21"
    inst = os.path.join(TRAIN, nm + ".json")
    data = json.load(open(inst, encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)

    print(f"== 원래 솔버(BEFORE) : {nm}, timelimit={tl}s ==", flush=True)
    t0 = time.time()
    sol = myalgorithm.algorithm(data, tl)
    dt = time.time() - t0
    res = utils.check_feasibility(data, sol)
    print(f"  feasible={res.get('feasible')} stage={res.get('stage')} "
          f"obj={res.get('objective')} (z1={res.get('obj1')}, z2={res.get('obj2')}, "
          f"z3={res.get('obj3')})  {dt:.0f}s", flush=True)

    json.dump(sol, open(os.path.join(OUT, f"original_{nm}.json"), "w"))
    tr, bay = ops_to_trace(data, sol["operations"], f"원래 솔버 {nm}", nm)
    out = os.path.join(OUT, f"cmp_{nm}_BEFORE_original_bay{bay}.html")
    write_viz(tr, out)
    print(f"  viz(BEFORE, bay {bay}, {tr['stats']['bay_blocks']} blocks): {out}", flush=True)


if __name__ == "__main__":
    main()
