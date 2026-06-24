"""Two read-only measurements feeding the z3 kill-test:

1. alpha calibration: in our best captured solutions, per-bay PEAK simultaneous
   bbox-area / bay-area -- the packing density our decoder actually realizes.
2. pref-headroom: if EVERY block went to its argmax-preference bay, per-bay
   area-time volume utilisation (sum area*P / bay_area*horizon) -- which
   instances even admit a near-pure preference assignment.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "results" / "capture"
INST = ROOT / "instances" / "train"


def bbox_areas(shape):
    """min over orientations of bbox area; shape = list of orientation dicts."""
    best = None
    for o in shape:
        xs, ys = [], []
        for layer in o["layers"]:
            for x, y in layer:
                xs.append(x); ys.append(y)
        a = (max(xs) - min(xs)) * (max(ys) - min(ys))
        best = a if best is None else min(best, a)
    return best


def best_solution(inst):
    best = None
    for d in CAP.iterdir():
        if not d.is_dir():
            continue
        f = d / f"{inst}.json"
        if not f.exists():
            continue
        try:
            j = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        m = j.get("met")
        if not m or not m.get("feas") or not j.get("solution"):
            continue
        if best is None or m["obj"] < best[0]:
            best = (m["obj"], j["solution"])
    return best


print(f"{'inst':9} {'bays':>4} | alpha: peak simultaneous area/bay_area in our "
      f"best sol (per bay) | pref-volume util if all blocks at argmax bay")
for i in range(1, 21):
    inst = f"prob_{i}"
    d = json.load(open(INST / f"{inst}.json", encoding="utf-8"))
    bays = d["bays"]
    blocks = d["blocks"]
    bay_area = [b["width"] * b["height"] for b in bays]
    area = [bbox_areas(b["shape"]) for b in blocks]

    # --- 1. alpha from our best capture ---------------------------------
    alphas = []
    bs = best_solution(inst)
    if bs:
        _, sol = bs
        # events: (t, +area, bay) / (t, -area, bay)
        ev = []
        for t, ops in sol["operations"].items():
            t = int(t)
            for op in ops:
                if op["type"] == "ENTRY":
                    ev.append((t, 0, op["bay_id"], area[op["block_id"]]))
                elif op["type"] == "EXIT":
                    ev.append((t, -1, op["bay_id"], area[op["block_id"]]))
        ev.sort(key=lambda e: (e[0], e[1]))  # EXIT before ENTRY at same t
        cur = [0.0] * len(bays)
        peak = [0.0] * len(bays)
        for t, kind, j, a in ev:
            cur[j] += a if kind == 0 else -a
            peak[j] = max(peak[j], cur[j])
        alphas = [round(p / ba, 2) for p, ba in zip(peak, bay_area)]

    # --- 2. pref-first volume utilisation --------------------------------
    vol = [0.0] * len(bays)
    lo, hi = 10**9, 0
    for b, a in zip(blocks, area):
        prefs = b["bay_preferences"]
        j = max(range(len(bays)), key=lambda k: prefs[k])
        vol[j] += a * b["processing_time"]
        lo = min(lo, b["release_time"]); hi = max(hi, b["due_date"])
    horizon = max(1, hi - lo)
    util = [round(v / (ba * horizon), 2) for v, ba in zip(vol, bay_area)]
    over = [f"bay{j}={u}" for j, u in enumerate(util) if u > 0.5]
    print(f"{inst:9} {len(bays):>4} | alpha={alphas} | prefutil={util}"
          f"{'  OVER: ' + ','.join(over) if over else ''}")
