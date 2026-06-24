"""Shared analysis core for OGC2026 hypothesis-testing / progress tools.

Loads instances + solutions, scores them with the OFFICIAL ``check_feasibility``
(eval-server mirror), and exposes per-block / per-bay decompositions of the
three objective components plus static (solver-free) structural diagnostics.

This module is READ-ONLY w.r.t. the solver: it never imports ``myalgorithm`` and
never touches ``src/`` or ``baseline/`` files except to import the official
``utils.check_feasibility``.  Every other tool in this toolkit builds on it.

Objective recap (from baseline/.../utils.py, weights w1>>w2,w3):
    obj1 = Sum max(0, exit_i - due_i)                          (tardiness)
    obj2 = floor( max_{j!=k} |u_j*load_j - u_k*load_k| ),      (imbalance)
             u_j = avg_bay_area / (W_j*H_j),  load_j = Sum workload in bay j
    obj3 = Sum_i ( max(prefs_i) - prefs_i[bay_i] )             (preference)
    objective = w1*obj1 + w2*obj2 + w3*obj3
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The official scorer (byte-identical to src/utils.py, synced to eval server).
_BASE = ROOT / "baseline" / "ogc2026" / "baseline"
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))
import utils  # noqa: E402  (check_feasibility + geometry)

check_feasibility = utils.check_feasibility


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def instance_path(name_or_path: str) -> Path:
    """Resolve 'prob_11', 'prob_11.json', or a full path to an instance file."""
    p = Path(name_or_path)
    if p.exists():
        return p
    stem = p.stem if p.suffix else name_or_path
    if not stem.endswith(".json"):
        stem_json = stem + ".json"
    else:
        stem_json = stem
    for pat in (f"instances/train/{stem_json}",
                f"instances/**/{stem_json}"):
        g = glob.glob(str(ROOT / pat), recursive=True)
        if g:
            return Path(sorted(g, key=len)[0])
    raise FileNotFoundError(f"instance not found: {name_or_path}")


def load_instance(name_or_path: str) -> dict:
    return json.loads(instance_path(name_or_path).read_text(encoding="utf-8"))


def load_solution(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_train_instances() -> list[str]:
    files = glob.glob(str(ROOT / "instances/train/prob_*.json"))
    return sorted((Path(f).stem for f in files),
                  key=lambda s: int(s.split("_")[-1]))


# --------------------------------------------------------------------------- #
# Scoring (official)
# --------------------------------------------------------------------------- #
def score(prob_info: dict, sol: dict) -> dict:
    """Return the full official report (feasible/stage/objective/obj1/2/3)."""
    return check_feasibility(prob_info, sol)


# --------------------------------------------------------------------------- #
# Solution normalisation:  operations dict -> per-block record
# --------------------------------------------------------------------------- #
def assignments(prob_info: dict, sol: dict) -> dict:
    """Reconstruct a per-block record from the operations dict.

    Returns {block_id: {bay, x, y, orient, entry, exit, release, due,
                        processing, workload}}.  Blocks missing an ENTRY or EXIT
    are still returned with whatever was found (None for the missing field).
    """
    ops = sol.get("operations", {})
    blocks = prob_info["blocks"]
    rec: dict[int, dict] = {}
    for tkey, op_list in ops.items():
        try:
            t = float(tkey)
        except (TypeError, ValueError):
            t = tkey
        for op in op_list:
            bid = op["block_id"]
            r = rec.setdefault(bid, {"bay": None, "x": None, "y": None,
                                     "orient": None, "entry": None,
                                     "exit": None})
            if op.get("type") == "ENTRY":
                r["entry"] = t
                r["bay"] = op.get("bay_id")
                r["x"] = op.get("x")
                r["y"] = op.get("y")
                r["orient"] = op.get("orient_idx")
            elif op.get("type") == "EXIT":
                r["exit"] = t
    for bid, r in rec.items():
        b = blocks[bid]
        r["release"] = b["release_time"]
        r["due"] = b["due_date"]
        r["processing"] = b["processing_time"]
        r["workload"] = b["workload"]
    return rec


# --------------------------------------------------------------------------- #
# Z1 : tardiness decomposition
# --------------------------------------------------------------------------- #
def per_block_tardiness(prob_info: dict, sol: dict) -> list:
    """List of dicts for every block, sorted by tardiness desc.

    Each: {block, bay, exit, due, slack_intrinsic, tardy, entry, release}.
    slack_intrinsic = due - release - processing  (>=0 means deadline reachable
    if it could enter at release and leave immediately -> any tardiness is
    induced by crane serialisation / layout, not by an impossible deadline).
    """
    rec = assignments(prob_info, sol)
    out = []
    for bid, r in rec.items():
        ex = r["exit"]
        tardy = max(0.0, (ex - r["due"])) if ex is not None else None
        out.append({
            "block": bid, "bay": r["bay"], "entry": r["entry"], "exit": ex,
            "release": r["release"], "due": r["due"],
            "processing": r["processing"],
            "slack_intrinsic": r["due"] - r["release"] - r["processing"],
            "tardy": tardy,
        })
    out.sort(key=lambda d: (-(d["tardy"] or -1), d["block"]))
    return out


# --------------------------------------------------------------------------- #
# Z2 : load imbalance decomposition
# --------------------------------------------------------------------------- #
def bay_loads(prob_info: dict, sol: dict) -> dict:
    """Per-bay workload, bay weight u_j, weighted load, and the worst pair.

    Mirrors the official obj2 = floor(max |u_j*load_j - u_k*load_k|).
    """
    rec = assignments(prob_info, sol)
    bays = prob_info["bays"]
    n = len(bays)
    loads = [0.0] * n
    for bid, r in rec.items():
        if r["bay"] is not None:
            loads[r["bay"]] += prob_info["blocks"][bid]["workload"]
    areas = [b["width"] * b["height"] for b in bays]
    avg = sum(areas) / n
    u = [avg / a for a in areas]
    weighted = [u[j] * loads[j] for j in range(n)]
    worst = (0, 0, 0.0)
    for j in range(n):
        for k in range(n):
            if j != k:
                d = abs(weighted[j] - weighted[k])
                if d > worst[2]:
                    worst = (j, k, d)
    return {
        "loads": loads, "u": u, "weighted": weighted,
        "obj2": math.floor(worst[2]) if n >= 2 else 0.0,
        "worst_pair": (worst[0], worst[1]),
        "worst_gap": worst[2],
    }


# --------------------------------------------------------------------------- #
# Z3 : preference deviation decomposition
# --------------------------------------------------------------------------- #
def pref_deviations(prob_info: dict, sol: dict) -> dict:
    """Per-block preference penalty (s_max - prefs[bay]) and the off-pref list."""
    rec = assignments(prob_info, sol)
    blocks = prob_info["blocks"]
    total = 0.0
    off = []
    for bid, r in rec.items():
        prefs = blocks[bid]["bay_preferences"]
        if r["bay"] is None:
            continue
        s_max = max(prefs)
        dev = s_max - prefs[r["bay"]]
        total += dev
        if dev > 0:
            off.append({"block": bid, "bay": r["bay"], "dev": dev,
                        "prefs": prefs})
    off.sort(key=lambda d: -d["dev"])
    return {"obj3": total, "n_off": len(off), "off": off}


# --------------------------------------------------------------------------- #
# Geometry (raw-shape based, no dependence on internal anchoring)
# --------------------------------------------------------------------------- #
def _poly_area(pts: list) -> float:
    """Shoelace area of a polygon ring."""
    n = len(pts)
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def _footprint_area(layers: list) -> float:
    """Area of the (x,y) union of all layers -- the true floor footprint.

    For multi-layer (crane-stacked) blocks the layers overlap in (x,y), so a
    naive sum of per-layer areas double-counts; the union is what occupies the
    bay floor and what the crane/collision constraints act on.  Uses shapely
    (already a utils dependency); falls back to the base (layer-0) area.
    """
    try:
        from shapely.geometry import Polygon as _P
        from shapely.ops import unary_union as _u
        polys = []
        for layer in layers:
            if len(layer) >= 3:
                p = _P(layer)
                if p.is_valid and p.area > 0:
                    polys.append(p)
        if polys:
            return float(_u(polys).area)
    except Exception:
        pass
    return _poly_area(layers[0]) if layers else 0.0


def orient_geometry(orient: dict) -> dict:
    """Footprint area (x,y union of layers), summed layer area, and bbox."""
    layers = orient["layers"]
    poly_sum = 0.0
    xs, ys = [], []
    for layer in layers:
        poly_sum += _poly_area(layer)
        for (x, y) in layer:
            xs.append(x)
            ys.append(y)
    w = (max(xs) - min(xs)) if xs else 0.0
    h = (max(ys) - min(ys)) if ys else 0.0
    return {"poly_area": _footprint_area(layers), "poly_sum": poly_sum,
            "bbox_w": w, "bbox_h": h, "bbox_area": w * h,
            "n_layers": len(layers)}


def block_min_area_orient(block: dict) -> dict:
    """The orientation index with smallest bbox area + its geometry."""
    best_i, best = 0, None
    for i, o in enumerate(block["shape"]):
        g = orient_geometry(o)
        if best is None or g["bbox_area"] < best["bbox_area"]:
            best, best_i = g, i
    best = dict(best)
    best["orient"] = best_i
    return best


# --------------------------------------------------------------------------- #
# Static (solver-free) instance diagnostics
# --------------------------------------------------------------------------- #
def intrinsic_z1_lb(prob_info: dict) -> float:
    """Sum max(0, release+processing-due): tardiness no schedule can avoid."""
    return sum(max(0.0, b["release_time"] + b["processing_time"] - b["due_date"])
               for b in prob_info["blocks"])


def _block_pref_bay(block: dict) -> int:
    prefs = block["bay_preferences"]
    return max(range(len(prefs)), key=lambda j: prefs[j])


def demand_peak(prob_info: dict, by_preference: bool = True) -> dict:
    """Per-bay peak area-demand (% of bay floor) under an all-enter-at-release,
    leave-at-due model.  Assigns each block to its preferred bay (argmax pref)
    when by_preference, using each block's min-area orientation footprint.

    A peak >100% means that bay is intrinsically over-capacity at some instant
    (serialisation forced -> tardiness floor), whereas <100% means the bay is
    area-feasible and any tardiness is a packing/sequencing artefact.
    """
    bays = prob_info["bays"]
    n = len(bays)
    bay_area = [b["width"] * b["height"] for b in bays]
    # Build per-bay event lists for both the bbox-footprint and the true
    # polygon-footprint demand models.
    ev_bbox = [[] for _ in range(n)]
    ev_foot = [[] for _ in range(n)]
    for block in prob_info["blocks"]:
        j = _block_pref_bay(block) if by_preference else 0
        g = block_min_area_orient(block)
        og = orient_geometry(block["shape"][g["orient"]])
        # block occupies [release, due] window in this all-eager model
        ev_bbox[j].append((block["release_time"], g["bbox_area"]))
        ev_bbox[j].append((block["due_date"], -g["bbox_area"]))
        ev_foot[j].append((block["release_time"], og["poly_area"]))
        ev_foot[j].append((block["due_date"], -og["poly_area"]))

    def _peak(ev):
        ev = sorted(ev, key=lambda e: (e[0], -e[1]))
        cur = pk = 0.0
        for (_t, da) in ev:
            cur += da
            pk = max(pk, cur)
        return pk

    peaks = []
    for j in range(n):
        pb = _peak(ev_bbox[j])
        pf = _peak(ev_foot[j])
        peaks.append({"bay": j, "bay_area": bay_area[j],
                      "peak_bbox": pb, "peak_foot": pf,
                      "pct": 100.0 * pb / bay_area[j] if bay_area[j] else 0.0,
                      "pct_foot": 100.0 * pf / bay_area[j] if bay_area[j] else 0.0})
    return {"per_bay": peaks,
            "max_pct": max((p["pct"] for p in peaks), default=0.0),
            "max_pct_foot": max((p["pct_foot"] for p in peaks), default=0.0)}


def bbox_fragmentation(prob_info: dict, sol: dict) -> dict:
    """Per-bay measure of rectangle (bbox) waste vs true polygon area, summed
    over resident blocks at their chosen orientation.  High waste means the
    bbox-conservative packer is leaving exploitable polygon headroom (a lever
    for area-feasible-but-still-tardy instances)."""
    rec = assignments(prob_info, sol)
    bays = prob_info["bays"]
    n = len(bays)
    poly = [0.0] * n
    bbox = [0.0] * n
    for bid, r in rec.items():
        j = r["bay"]
        oi = r["orient"]
        if j is None or oi is None:
            continue
        g = orient_geometry(prob_info["blocks"][bid]["shape"][oi])
        poly[j] += g["poly_area"]
        bbox[j] += g["bbox_area"]
    out = []
    for j in range(n):
        area = bays[j]["width"] * bays[j]["height"]
        out.append({"bay": j, "poly": poly[j], "bbox": bbox[j],
                    "bay_area": area,
                    "waste": bbox[j] - poly[j],
                    "waste_pct_of_bay": (100.0 * (bbox[j] - poly[j]) / area)
                    if area else 0.0})
    return {"per_bay": out}


# --------------------------------------------------------------------------- #
# Convenience: one-line objective tuple
# --------------------------------------------------------------------------- #
def obj_tuple(prob_info: dict, sol: dict) -> tuple:
    """(feasible, objective, obj1, obj2, obj3) for quick comparisons."""
    r = score(prob_info, sol)
    if not r.get("feasible"):
        return (False, None, None, None, None)
    return (True, r["objective"], r["obj1"], r["obj2"], r["obj3"])
