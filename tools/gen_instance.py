"""
gen_instance.py -- Synthetic OGC 2026 instance generator

Usage:
    python tools/gen_instance.py \
        --n 10 --m 2 --density 0.4 --regime w1 --tightness 0.5 \
        --max-layers 2 --seed 1 --out instances/gen/gen_n10_loose_w1_s1.json

Every call with the same arguments produces a byte-identical JSON file.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _rotate90(verts: list[list[float]]) -> list[list[float]]:
    """Rotate vertices 90° CCW: (x, y) -> (-y, x)."""
    return [[-y, x] for x, y in verts]


def _mirror_x(verts: list[list[float]]) -> list[list[float]]:
    """Mirror across y-axis: (x, y) -> (-x, y)."""
    return [[-x, y] for x, y in verts]


def _anchor(verts: list[list[float]]) -> list[list[float]]:
    """Translate so bounding-box min corner is at (0, 0)."""
    if not verts:
        return verts
    min_x = min(v[0] for v in verts)
    min_y = min(v[1] for v in verts)
    return [[x - min_x, y - min_y] for x, y in verts]


def _anchor_layers(layers: list[list[list[float]]]) -> list[list[list[float]]]:
    """Translate ALL layers by the same offset so union bbox min = (0,0).
    This preserves inter-layer relative positions."""
    all_verts = [v for l in layers for v in l]
    if not all_verts:
        return layers
    min_x = min(v[0] for v in all_verts)
    min_y = min(v[1] for v in all_verts)
    return [[[x - min_x, y - min_y] for x, y in l] for l in layers]


def _bbox(verts: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_wh(verts: list[list[float]]) -> tuple[float, float]:
    bx0, by0, bx1, by1 = _bbox(verts)
    return bx1 - bx0, by1 - by0


def _polygon_area(verts: list[list[float]]) -> float:
    """Shoelace formula."""
    n = len(verts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += verts[i][0] * verts[j][1]
        area -= verts[j][0] * verts[i][1]
    return abs(area) / 2.0


# ---------------------------------------------------------------------------
# Irregular polygon builder
# ---------------------------------------------------------------------------

def _make_notched_rect(rng: random.Random, w: float, h: float
                       ) -> list[list[float]]:
    """
    Make a rectangle with one rectangular notch cut from one corner.
    Always produces a simple, non-self-intersecting polygon with >= 6 vertices.
    Result is anchored so bbox min = (0,0); first vertex is (0,0).
    """
    # Notch size: between 20% and 40% of each dimension
    nw = rng.uniform(0.2, 0.4) * w
    nh = rng.uniform(0.2, 0.4) * h
    # Cut from top-right corner
    verts = [
        [0.0,    0.0],
        [w,      0.0],
        [w,      h - nh],
        [w - nw, h - nh],
        [w - nw, h],
        [0.0,    h],
    ]
    return verts


def _scale_polygon(verts: list[list[float]], scale: float) -> list[list[float]]:
    return [[x * scale, y * scale] for x, y in verts]


def _inset_polygon(verts: list[list[float]], margin: float
                   ) -> list[list[float]] | None:
    """
    Simple inset: shrink the polygon toward its centroid by `margin`.
    Returns None if the result is degenerate.
    """
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    result = []
    for x, y in verts:
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        if dist < margin * 1.5:
            return None
        f = (dist - margin) / dist
        result.append([cx + dx * f, cy + dy * f])
    return result


def _make_8_orientations(base_layer: list[list[float]],
                         extra_layers: list[list[list[float]]]
                         ) -> list[dict]:
    """
    Generate the 8 D4 orientations (4 rotations × 2 mirrors).
    Each orientation entry has shape[i]["layers"] with correctly aligned layers.
    All orientations are pre-anchored so union bbox min = (0,0).
    """
    orientations = []

    def _apply_transform(verts_list: list[list[list[float]]],
                         transform_fn) -> list[list[list[float]]]:
        return [transform_fn(v) for v in verts_list]

    all_base = [base_layer] + extra_layers  # list of vertex lists

    transforms = [
        # identity
        lambda v: v,
        # 90° CCW
        _rotate90,
        # 180°
        lambda v: _rotate90(_rotate90(v)),
        # 270° CCW
        lambda v: _rotate90(_rotate90(_rotate90(v))),
        # mirror x
        _mirror_x,
        # mirror x + 90° CCW
        lambda v: _rotate90(_mirror_x(v)),
        # mirror x + 180°
        lambda v: _rotate90(_rotate90(_mirror_x(v))),
        # mirror x + 270° CCW
        lambda v: _rotate90(_rotate90(_rotate90(_mirror_x(v)))),
    ]

    for idx, tf in enumerate(transforms):
        transformed_layers = [tf(layer) for layer in all_base]
        anchored_layers = _anchor_layers(transformed_layers)
        # Ensure first vertex of first layer is [0.0, 0.0]
        if anchored_layers and anchored_layers[0]:
            ref = anchored_layers[0][0]
            if abs(ref[0]) > 1e-9 or abs(ref[1]) > 1e-9:
                dx, dy = -ref[0], -ref[1]
                anchored_layers = [
                    [[x + dx, y + dy] for x, y in layer]
                    for layer in anchored_layers
                ]
        orientations.append({
            "orientation": idx,
            "layers": anchored_layers,
        })

    return orientations


# ---------------------------------------------------------------------------
# Block bounding-box check (does it fit in some bay?)
# ---------------------------------------------------------------------------

def _block_min_bbox(block_shape: list[dict]) -> tuple[float, float]:
    """Return the minimum (width, height) across all 8 orientations."""
    min_w, min_h = float("inf"), float("inf")
    for entry in block_shape:
        all_verts = [v for layer in entry["layers"] for v in layer]
        if not all_verts:
            continue
        bx0, by0, bx1, by1 = _bbox(all_verts)
        w = bx1 - bx0
        h = by1 - by0
        if w < min_w:
            min_w = w
        if h < min_h:
            min_h = h
    return min_w, min_h


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_instance(
    n: int,
    m: int,
    density: float,
    regime: str,
    tightness: float,
    max_layers: int,
    seed: int,
    rel_window: int | None = None,
) -> dict:
    """
    Generate a single OGC 2026 problem instance.

    Parameters
    ----------
    n          : Number of blocks.
    m          : Number of bays.
    density    : Target ratio of total block footprint area / total bay area.
    regime     : Which objective weight dominates: 'w1', 'w2', or 'w3'.
    tightness  : Due-date tightness in [0,1]; 0 = tightest (slack=0),
                 1 = loosest (slack = large multiple of processing_time).
    max_layers : Maximum number of layers per block (1..max_layers).
    seed       : RNG seed for full reproducibility.
    """
    rng = random.Random(seed)

    # ------------------------------------------------------------------
    # 1. Bay sizes
    # ------------------------------------------------------------------
    # Use moderate fixed sizes scaled with m so total area is predictable.
    # Width 60..100, height 15..25
    bays = []
    for _ in range(m):
        w = rng.randint(60, 100)
        h = rng.randint(15, 25)
        bays.append({"width": w, "height": h})

    total_bay_area = sum(b["width"] * b["height"] for b in bays)

    # ------------------------------------------------------------------
    # 2. Block shapes
    # ------------------------------------------------------------------
    # Target total footprint area for all blocks.
    target_total_area = density * total_bay_area
    target_per_block = target_total_area / n

    # Each block's base polygon fits within some bay. We generate a
    # notched rectangle of size w x h where the bounding box is chosen
    # so that the block comfortably fits in the smallest bay in some orientation.
    min_bay_w = min(b["width"] for b in bays)
    min_bay_h = min(b["height"] for b in bays)

    # Block width: between 10% and 40% of min bay width
    # Block height: between 30% and 70% of min bay height
    # We scale to match target_per_block area.

    blocks = []
    for bi in range(n):
        # Choose block proportions
        raw_w = rng.uniform(0.1, 0.35) * min_bay_w
        raw_h = rng.uniform(0.25, 0.60) * min_bay_h

        # Scale so that approximate footprint area = target_per_block
        # Notched rect area ≈ 0.8 * w * h (after notch removal ~20%)
        approx_area = 0.8 * raw_w * raw_h
        if approx_area < 1e-6:
            scale = 1.0
        else:
            scale = math.sqrt(target_per_block / approx_area)

        w = raw_w * scale
        h = raw_h * scale

        # Safety: block must fit in at least one bay in at least one orientation.
        # Clamp: ensure w <= min_bay_w * 0.9 and h <= min_bay_h * 0.9
        # (in the worst orientation the bounding box is ~max(w,h) × min(w,h))
        max_allowed = min(min_bay_w, min_bay_h) * 0.85
        if max(w, h) > max_allowed:
            sf = max_allowed / max(w, h)
            w *= sf
            h *= sf

        # At minimum size: ensure block is non-trivial
        w = max(w, 2.0)
        h = max(h, 2.0)

        base_layer = _make_notched_rect(rng, w, h)

        # Extra layers (insets of the base layer, for physical stacking)
        n_layers = rng.randint(1, max_layers)
        extra_layers = []
        margin_step = min(w, h) * 0.08
        prev_layer = base_layer
        for li in range(1, n_layers):
            inset = _inset_polygon(prev_layer, margin_step * (li * 0.5 + 1))
            if inset is None or _polygon_area(inset) < 1.0:
                break
            extra_layers.append(inset)
            prev_layer = inset

        shape_entries = _make_8_orientations(base_layer, extra_layers)

        # ------------------------------------------------------------------
        # 3. Timing
        # ------------------------------------------------------------------
        # Blocks span a scheduling horizon of roughly 3x processing_time
        processing_time = rng.randint(3, 12)
        # rel_window controls how clustered the release times are.  The default
        # (n*3) spreads them so blocks rarely contend (-> Z1=0 is easy).  A small
        # window clusters releases, so many blocks are active at once and a bay
        # cannot hold them all spatially -> forced serialization -> tardiness whose
        # magnitude depends on how the blocks are spread across bays (the Z1 lever).
        _rw = n * 3 if rel_window is None else max(0, rel_window)
        release_time = rng.randint(0, _rw)
        # slack: tightness=1 => slack = 2*pt; tightness=0 => slack = 0
        slack = int(tightness * 2 * processing_time)
        due_date = release_time + processing_time + slack
        workload = rng.randint(10, 150)

        # ------------------------------------------------------------------
        # 4. Bay preferences
        # ------------------------------------------------------------------
        # Sum must be exactly 100.
        prefs = [rng.randint(1, 10) for _ in range(m)]
        total_pref = sum(prefs)
        # Scale to ~100, then fix rounding
        prefs = [int(round(p * 100 / total_pref)) for p in prefs]
        diff = 100 - sum(prefs)
        # Adjust the largest entry
        max_idx = prefs.index(max(prefs))
        prefs[max_idx] += diff
        assert sum(prefs) == 100, f"Preferences sum = {sum(prefs)}"

        # For w3-dominant regime, skew preferences more
        if regime == "w3":
            prefs = sorted(prefs, reverse=True)
            # Make first pref large
            prefs[0] = rng.randint(60, 85)
            remainder = 100 - prefs[0]
            for i in range(1, m):
                if i == m - 1:
                    prefs[i] = remainder - sum(prefs[1:i])
                else:
                    prefs[i] = max(1, int(remainder / (m - 1) + rng.randint(-3, 3)))
            # Fix rounding again
            diff2 = 100 - sum(prefs)
            prefs[0] += diff2
            # Clamp negatives
            for i in range(m):
                if prefs[i] < 1:
                    prefs[i] = 1
            diff3 = 100 - sum(prefs)
            prefs[0] += diff3

        blocks.append({
            "release_time": release_time,
            "due_date": due_date,
            "processing_time": processing_time,
            "workload": workload,
            "bay_preferences": prefs,
            "shape": shape_entries,
        })

    # ------------------------------------------------------------------
    # 5. Weights
    # ------------------------------------------------------------------
    if regime == "w1":
        weights = {"w1": 2667, "w2": 7, "w3": 20}
    elif regime == "w2":
        weights = {"w1": 7, "w2": 2667, "w3": 20}
    else:  # w3
        weights = {"w1": 7, "w2": 20, "w3": 2667}

    # ------------------------------------------------------------------
    # 6. Instance name
    # ------------------------------------------------------------------
    name = f"gen_n{n}_m{m}_d{int(density*100)}_r{regime}_t{int(tightness*10)}_s{seed}"

    return {
        "name": name,
        "bays": bays,
        "blocks": blocks,
        "weights": weights,
    }


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def validate_instance(prob_info: dict, strict: bool = True) -> list[str]:
    """
    Light schema validation (no solver call).
    Returns a list of error strings; empty means OK.
    """
    errors = []
    bays = prob_info.get("bays", [])
    blocks = prob_info.get("blocks", [])
    weights = prob_info.get("weights", {})
    m = len(bays)

    for k in ("w1", "w2", "w3"):
        if k not in weights:
            errors.append(f"Missing weight: {k}")

    for bi, blk in enumerate(blocks):
        for key in ("release_time", "due_date", "processing_time", "workload",
                    "bay_preferences", "shape"):
            if key not in blk:
                errors.append(f"Block {bi}: missing '{key}'")

        prefs = blk.get("bay_preferences", [])
        if len(prefs) != m:
            errors.append(f"Block {bi}: bay_preferences length {len(prefs)} != {m}")
        if sum(prefs) != 100:
            errors.append(f"Block {bi}: bay_preferences sum={sum(prefs)} != 100")

        pt = blk.get("processing_time", 0)
        rt = blk.get("release_time", 0)
        dd = blk.get("due_date", 0)
        if pt < 1:
            errors.append(f"Block {bi}: processing_time={pt} < 1")
        if dd < rt + pt:
            errors.append(f"Block {bi}: due_date={dd} < release_time+processing_time={rt+pt}")

        shape = blk.get("shape", [])
        if len(shape) != 8:
            errors.append(f"Block {bi}: shape has {len(shape)} entries (expected 8)")
        for si, entry in enumerate(shape):
            if not entry.get("layers"):
                errors.append(f"Block {bi} shape[{si}]: no layers")

        # Check block fits in at least one bay
        if strict and shape:
            fits = False
            for entry in shape:
                all_verts = [v for layer in entry["layers"] for v in layer]
                if not all_verts:
                    continue
                bx0, by0, bx1, by1 = _bbox(all_verts)
                bw, bh = bx1 - bx0, by1 - by0
                for bay in bays:
                    if bw <= bay["width"] and bh <= bay["height"]:
                        fits = True
                        break
                if fits:
                    break
            if not fits:
                errors.append(f"Block {bi}: does not fit in any bay in any orientation")

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate OGC 2026 synthetic instances.")
    ap.add_argument("--n", type=int, default=10, help="Number of blocks")
    ap.add_argument("--m", type=int, default=2, help="Number of bays")
    ap.add_argument("--density", type=float, default=0.4,
                    help="Total block area / total bay area (default 0.4)")
    ap.add_argument("--regime", choices=["w1", "w2", "w3"], default="w1",
                    help="Dominant objective weight")
    ap.add_argument("--tightness", type=float, default=0.5,
                    help="Due-date tightness [0,1]; 0=tightest, 1=loosest")
    ap.add_argument("--max-layers", type=int, default=2,
                    help="Maximum layers per block (default 2)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed")
    ap.add_argument("--rel-window", type=int, default=None,
                    help="Release-time window upper bound (default n*3). Small "
                         "values cluster releases -> temporal congestion/tardiness.")
    ap.add_argument("--out", type=str, required=True,
                    help="Output JSON path")
    args = ap.parse_args()

    prob_info = generate_instance(
        n=args.n,
        m=args.m,
        density=args.density,
        regime=args.regime,
        tightness=args.tightness,
        max_layers=args.max_layers,
        seed=args.seed,
        rel_window=args.rel_window,
    )

    errors = validate_instance(prob_info)
    if errors:
        print("[gen_instance] VALIDATION ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(prob_info, indent=2), encoding="utf-8")
    print(f"[gen_instance] wrote {out_path}  "
          f"(n={args.n}, m={args.m}, density={args.density:.2f}, "
          f"regime={args.regime}, tightness={args.tightness:.2f}, seed={args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
