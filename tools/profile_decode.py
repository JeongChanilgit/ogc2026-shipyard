#!/usr/bin/env python3
"""
profile_decode.py -- READ-ONLY cProfile of ONE clean per-bay crane-safe decode.

Imports the solver decoder (edits nothing) exactly like validate_clean_decode.py /
resequence_gain.py.  Profiles a SINGLE bay of prob_6 with deadline=None (clean,
untruncated) using the EDD ordering, with OGC_CRANE_COEXIT=1 (the fixed flag).

Usage:  python tools/profile_decode.py [bay_idx]   (default bay 0)
"""
import os, sys, json, cProfile, pstats, io, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Same switches as the existing standalone decode tools, plus the fixed co-exit flag.
os.environ.setdefault("OGC_ATCR_SEED", "1")
os.environ.setdefault("OGC_CRANE_SAFE", "1")
os.environ["OGC_CRANE_COEXIT"] = "1"        # the fixed flag (slightly slower)
os.environ.setdefault("OGC_FAST_CRANE", "0")  # profile the DEFAULT (shipped) path

from utils import Bay                                    # noqa: E402
from myalgorithm import _decode_bay, _orderings, _bay_tardiness  # noqa: E402

INST = ROOT / "instances" / "train" / "prob_6.json"
SOL  = ROOT / "results" / "z1_exp_B" / "sol_prob_6__base.json"

BAY_IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 0


def load_blocks_by_bay(sol):
    rec = {}
    for t_str, ops in sol["operations"].items():
        for op in ops:
            r = rec.setdefault(op["block_id"], {})
            if op["type"] == "ENTRY":
                r["bay"] = op["bay_id"]
    by_bay = {}
    for bid, r in rec.items():
        if "bay" in r:
            by_bay.setdefault(r["bay"], []).append(bid)
    return by_bay


def main():
    prob = json.loads(INST.read_text())
    sol  = json.loads(SOL.read_text())
    blocks_data = prob["blocks"]
    bays = [Bay.from_dict(d, j) for j, d in enumerate(prob["bays"])]
    by_bay = load_blocks_by_bay(sol)

    ids = by_bay[BAY_IDX]
    bay = bays[BAY_IDX]
    # EDD ordering (first of _orderings) -- one representative clean decode.
    order = list(_orderings(list(ids), blocks_data, allow_alt=True)[0])
    print(f"Profiling bay {BAY_IDX}: n={len(ids)} blocks, "
          f"bay {bay.width}x{bay.height}, COEXIT=1, FAST_CRANE=0, deadline=None",
          flush=True)

    pr = cProfile.Profile()
    t0 = time.monotonic()
    pr.enable()
    res, forced = _decode_bay(bay, BAY_IDX, order, blocks_data, deadline=None)
    pr.disable()
    wall = time.monotonic() - t0
    tard = _bay_tardiness(res, blocks_data) if res else float("inf")
    print(f"decode wall={wall:.1f}s  placed={len(res) if res else 0}  "
          f"forced={len(forced)}  tard={tard:.0f}\n", flush=True)

    st = pstats.Stats(pr)
    # cache stats for poly cache hit rate
    try:
        from utils import _poly_from_verts_cached
        ci = _poly_from_verts_cached.cache_info()
        print(f"_poly_from_verts_cached cache: {ci}\n", flush=True)
    except Exception as e:
        print("cache_info unavailable:", e)

    for sortkey, label in (("cumulative", "BY CUMULATIVE TIME"),
                           ("tottime", "BY TOTAL (OWN) TIME")):
        buf = io.StringIO()
        s = pstats.Stats(pr, stream=buf)
        s.sort_stats(sortkey).print_stats(18)
        print("=" * 100)
        print(label)
        print("=" * 100)
        print(buf.getvalue())


if __name__ == "__main__":
    main()
