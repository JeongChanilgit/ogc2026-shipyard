"""report_data.py — prob_38 파이프라인을 1회 실행해 *시각 리포트용 데이터*를 JSON 덤프.

검증 config(near-접촉 D=2 + diverse + fit=ov)로 실행. 단계별 시간·z, 베이별 배치 블록
(x,y,orient,entry,exit,due,footprint-ring), 혼잡시각, 후보 캡처를 모은다.
출력: out/report_data.json  (이걸로 ui-designer 가 시각 HTML 조립)
"""
from __future__ import annotations

import os

os.environ.setdefault("OGC_FIT", "ov")
os.environ["OGC_DIVERSE"] = "1"
os.environ["OGC_CONTACT_D"] = "2"
os.environ["OGC_WALL_W"] = "1"
os.environ["OGC_TOSS"] = "0"
os.environ["OGC_PACK_SWAP"] = "0"
os.environ["OGC_GUIDE_ATLOOSE"] = "0"
os.environ["OGC_STAGES"] = "1"
os.environ.setdefault("PYTHONUTF8", "1")

import json  # noqa: E402
import sys  # noqa: E402

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

import temporal_pack as tp  # noqa: E402
import unified_greedy as ug  # noqa: E402
from decomp_diag import footprint, components  # noqa: E402

NM = "prob_38"
TL = 200.0
ORIG = {"obj": 91107711, "z1": 6651, "z2": 2964, "z3": 8080}


def _ring(poly):
    try:
        g = poly
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        return [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords]
    except Exception:
        return []


def main():
    path = os.path.join(THIS, "..", "instances", "train", NM + ".json")
    data = json.load(open(path, encoding="utf-8"))
    blocks, bays = data["blocks"], data["bays"]
    tp._CAP = {"min_cands": 8, "min_present": 12, "need_ov": True, "counts": []}
    res, dist, cpsat, dt = ug.unified(data, TL, path)
    sol = res.get("_solution")

    # 베이별 배치 블록 레코드
    per_bay = {}
    spans = {}
    for stk, ops in sol["operations"].items():
        for op in ops:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                j = int(op["bay_id"])
                f = footprint(blocks[bid], int(op.get("orient_idx", 0)), op.get("x", 0), op.get("y", 0))
                rec = {"bid": bid, "x": op.get("x", 0), "y": op.get("y", 0),
                       "o": int(op.get("orient_idx", 0)), "entry": int(float(stk)),
                       "due": blocks[bid].get("due_date"), "P": blocks[bid].get("processing_time"),
                       "ring": _ring(f) if f is not None else []}
                per_bay.setdefault(j, []).append(rec)
                spans[bid] = [int(float(stk)), None]
            else:
                if bid in spans:
                    spans[bid][1] = int(float(stk))
    # exit 채우기 + tardy
    for j, recs in per_bay.items():
        for r in recs:
            e, x = spans[r["bid"]]
            r["exit"] = x if x is not None else e + (r["P"] or 1)
            r["tardy"] = r["exit"] > r["due"]

    # 베이별 혼잡(최대 동시공존) 시각
    busy = {}
    for j, recs in per_bay.items():
        evs = []
        for r in recs:
            evs += [(r["entry"], 1), (r["exit"], -1)]
        evs.sort()
        cur = mx = 0
        bt = 0
        for t, d in evs:
            cur += d
            if cur > mx:
                mx = cur
                bt = t
        sp = {r["bid"]: (r["entry"], r["exit"]) for r in recs}
        bbf = [(r["bid"], footprint(blocks[r["bid"]], r["o"], r["x"], r["y"])) for r in recs]
        ncomp = len(components(bbf, sp))
        busy[j] = {"max_coexist": mx, "time": bt, "st_components": ncomp}

    out = {
        "instance": NM, "tl": TL, "total_s": round(dt, 1),
        "N": len(blocks), "m": len(bays),
        "weights": data["weights"],
        "bays": [{"id": j, "W": b["width"], "H": b["height"],
                  "max_layer": max(len(o["layers"]) for o in b.get("shape", [{"layers": [[]]}]))
                  if False else 1} for j, b in enumerate(bays)],
        "bay_dims": [{"id": j, "W": b["width"], "H": b["height"]} for j, b in enumerate(bays)],
        "stages": list(ug.STAGES),
        "final": {"obj": res.get("objective"), "z1": res.get("obj1"),
                  "z2": res.get("obj2"), "z3": res.get("obj3")},
        "orig": ORIG,
        "per_bay": {str(j): recs for j, recs in per_bay.items()},
        "busy": {str(j): v for j, v in busy.items()},
        "candidates": tp._CAP.get("out"),
        "cand_counts": tp._CAP.get("counts", []),
    }
    outp = os.path.join(THIS, "out", "report_data.json")
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"wrote {outp}  obj={out['final']['obj']:,}  bays={list(per_bay.keys())} "
          f"blocks/bay={[len(per_bay[j]) for j in sorted(per_bay)]}  busy={out['busy']}", flush=True)


if __name__ == "__main__":
    main()
