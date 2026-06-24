"""Finer-raster geometry validation (structural lever, 2026-06-14 PM).

Measured: the unit-cell raster superset over-estimates the true polygon footprint
by ~35% (raster/poly 1.31-1.40). Hypothesis: that conservativeness creates FALSE
crane conflicts -> blocks the decoder wrongly can't place at entry=R -> tardiness
/ spill -> inflated z3. A FINER raster (cells at 1/S, still an outward-rounded
SUPERSET => still sound) removes most false conflicts -> denser crane-safe packing.

KEY trick: `baseline_greedy._rasterize_layer_cells` is sound at ANY scale, so
feeding it verts*S yields a sound 1/S-resolution cover for free. Positions stay
ORIGINAL-integer (legal); only the cell shift scales by S.

This prototype compares per-bay fixed-time (entry=R) decode tardiness for S=1
(== current raster) vs S=2,3 on the over-subscribed loss bays. Lower tardiness
under finer S == the lever is real.

  conda run -n ogc2025 python notes/devlog/probe_fine_geom.py prob_3 prob_11 prob_17
"""
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as A          # noqa: E402  (poisons path -> re-pin src)
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M           # noqa: E402
import fastfloor as FF            # noqa: E402
from utils import Bay, Block      # noqa: E402
from baseline_greedy import _rasterize_layer_cells  # noqa: E402


def _fine_world_cells(block_obj, S):
    """Fine (1/S) world cells of a placed block, per layer (sound superset)."""
    return [_rasterize_layer_cells([(x * S, y * S) for (x, y) in layer])
            for layer in block_obj.layers_at_pos()]


def _fine_local_geom(blk, S):
    """Per-orientation fine local cells + cell bbox + poly bbox + n_layers."""
    from utils import _resolve_layers
    from baseline_greedy import _block_bbox
    g = []
    for oi in range(len(blk.get("shape", []) or [])):
        try:
            layers = [_rasterize_layer_cells([(x * S, y * S) for (x, y) in l])
                      for l in _resolve_layers(blk["shape"][oi]["layers"])]
        except Exception:
            layers = []
        if not layers or not all(layers):
            g.append(None); continue
        allc = [c for lay in layers for c in lay]
        cbox = (min(c[0] for c in allc), min(c[1] for c in allc),
                max(c[0] for c in allc), max(c[1] for c in allc))
        g.append((layers, cbox, _block_bbox(blk, oi), len(layers)))
    return g


def decode_bay_fine(bay, bay_idx, members, blocks, S, deadline):
    """Fixed-time (entry=R) per-bay decode with 1/S raster geometry, integer
    positions, BL first-feasible. Mirrors the structure of the production decode
    so the ONLY difference vs S=1 is the cell resolution. Returns tardiness."""
    order = sorted(members, key=lambda b: (int(blocks[b]["due_date"]),
                                           int(blocks[b]["release_time"]),
                                           -FF._min_bbox_area(blocks[b])))
    W, H = bay.width, bay.height
    placed = []           # {a,e,layers(fine world),n,cbox(fine),pbox(orig)}
    tard = 0.0
    geom_cache = {}
    for b in order:
        if time.monotonic() >= deadline - 0.3:
            return None
        blk = blocks[b]
        R = int(blk["release_time"]); P = int(blk["processing_time"])
        D = int(blk["due_date"])
        g = geom_cache.get(b)
        if g is None:
            g = _fine_local_geom(blk, S); geom_cache[b] = g

        def _try(aB, eB):
            At = FF._ft_interacting(placed, aB, eB)
            # candidate x/y anchors (walls + placed edges), BL order
            best = None
            for oi, gg in enumerate(g):
                if gg is None:
                    continue
                layers, cb, pb, nB = gg
                if pb[2] - pb[0] > W + 1e-9 or pb[3] - pb[1] > H + 1e-9:
                    continue
                xs = {int(math.ceil(-pb[0] - 1e-9)), int(math.floor(W - pb[2] + 1e-9))}
                for Apl in At:
                    e = int(math.ceil(Apl["pbox"][2] - pb[0] - 1e-9)); xs.add(e); xs.add(e + 1)
                    w = int(math.floor(Apl["pbox"][0] - pb[2] + 1e-9)); xs.add(w); xs.add(w - 1)
                cset = []
                for dx in xs:
                    x0 = dx + pb[0]; x1 = dx + pb[2]
                    if x0 < -1e-9 or x1 > W + 1e-9:
                        continue
                    dys = {int(math.ceil(-pb[1] - 1e-9))}
                    for Apl in At:
                        apb = Apl["pbox"]
                        if apb[0] < x1 - 1e-9 and x0 < apb[2] - 1e-9:
                            d = int(math.ceil(apb[3] - pb[1] - 1e-9)); dys.add(d); dys.add(d + 1)
                    for dy in dys:
                        if dy + pb[1] < -1e-9 or dy + pb[3] > H + 1e-9:
                            continue
                        cset.append((dy + pb[1], dx + pb[0], oi, dx, dy))
                cset.sort()
                for _, _, oi2, dx, dy in cset:
                    # crane screen with fine cells, shift scaled by S
                    ok = True
                    for Apl in At:
                        if not FF._ft_pair_ok(Apl, aB, eB, layers, dx * S, dy * S, nB):
                            ok = False; break
                    if not ok:
                        continue
                    # exact bay containment via Block (original coords)
                    bl_obj = Block(b, blk, dx, dy, oi2)
                    if not bay.contains_block(bl_obj):
                        continue
                    wlayers = _fine_world_cells(bl_obj, S)
                    # SOUND re-verify with world fine cells (no shift) -- the
                    # shifted-local screen can mismatch (float verts), so the
                    # placed block's true world cells must clear every co-present
                    # A (superset => never false-accepts a real overlap).
                    okv = True
                    for Apl in At:
                        if not FF._ft_pair_ok(Apl, aB, eB, wlayers, 0, 0, len(wlayers)):
                            okv = False; break
                    if not okv:
                        continue
                    allc = [c for lay in wlayers for c in lay]
                    wcb = (min(c[0] for c in allc), min(c[1] for c in allc),
                           max(c[0] for c in allc), max(c[1] for c in allc)) if allc else (0, 0, -1, -1)
                    return (dx, dy, oi2, wlayers, wcb, pb)
            return best
        aB, eB = R, R + P
        pos = _try(aB, eB)
        if pos is None:
            for t in sorted({Apl["e"] for Apl in placed if Apl["e"] > R}):
                aB, eB = t, t + P
                pos = _try(aB, eB)
                if pos is not None:
                    break
        if pos is None:
            aB = max([R] + [Apl["e"] for Apl in placed]); eB = aB + P
            pos = _try(aB, eB)
            if pos is None:
                return None
        dx, dy, oi2, wlayers, wcb, pb = pos
        placed.append({"a": aB, "e": eB, "n": len(wlayers), "layers": wlayers,
                       "cbox": wcb,
                       "pbox": (pb[0] + dx, pb[1] + dy, pb[2] + dx, pb[3] + dy)})
        tard += max(0.0, eB - D)
    return tard


def main():
    import uconstruct as UC
    insts = sys.argv[1:] or ["prob_3", "prob_11", "prob_17"]
    for inst in insts:
        prob = A.load_instance(inst)
        bl = prob["blocks"]
        bays = [Bay.from_dict(d, i) for i, d in enumerate(prob["bays"])]
        nb = len(bays)
        ar = [prob["bays"][j]["width"] * prob["bays"][j]["height"] for j in range(nb)]
        avg = sum(ar) / nb; bu = [avg / a for a in ar]
        feas = M._feasible_bays(bl, bays); feas = [(f if f else list(range(nb))) for f in feas]
        bt = M._cpsat_assignment(prob, bays, feas, bu, time_budget=8.0)
        if bt is None:
            bt = [max(range(nb), key=lambda j: bl[b]["bay_preferences"][j]) for b in range(len(bl))]
        members = {j: [b for b in range(len(bl)) if bt[b] == j] for j in range(nb)}
        print(f"\n=== {inst}  bays={nb} ===")
        print(f"{'bay':>4}{'n':>5}{'S1_tard':>9}{'S2_tard':>9}{'S3_tard':>9}   note")
        for j in range(nb):
            mem = members[j]
            if len(mem) < 2:
                continue
            t1 = decode_bay_fine(bays[j], j, mem, bl, 1, time.monotonic() + 20)
            t2 = decode_bay_fine(bays[j], j, mem, bl, 2, time.monotonic() + 30)
            t3 = decode_bay_fine(bays[j], j, mem, bl, 3, time.monotonic() + 40)
            def f(x): return f"{x:.0f}" if x is not None else "FAIL"
            best = min(x for x in (t1, t2, t3) if x is not None)
            note = "  <<FINER HELPS" if (t1 is not None and best < t1 - 1e-6) else ""
            print(f"{j:>4}{len(mem):>5}{f(t1):>9}{f(t2):>9}{f(t3):>9}{note}")


if __name__ == "__main__":
    main()
