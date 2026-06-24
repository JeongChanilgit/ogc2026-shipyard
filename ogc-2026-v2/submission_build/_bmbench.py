"""_bmbench.py -- BITMASK precompute benchmark (NEXT-FIRST #1, HANDOFF-2026-06-24-v6v7).

Directly calls v7/v3pp crane_repack_bay on prob_38's biggest bay, A/B-ing the
precompute pre-filter across 4 arms:
  neither  : no filter (all shapely)            -- baseline
  AABB     : OGC_PRECOMP_AABB=1                 -- current production
  AABB+BM  : AABB + OGC_PRECOMP_BITMASK=1       -- submission candidate
  BMonly   : bitmask without AABB

Two questions (HANDOFF):
  (a) SAFETY  : n_stored (disjunction count) IDENTICAL across all arms?
                (filters only skip all-False combos -> output must be unchanged)
  (b) SPEED   : is AABB+BM's precompute_wall < AABB's?  (does bitmask pay for itself)

Measured on the SAME greedy start (shared `cur`) so candidate set is identical;
precompute is single-threaded deterministic compute (wall jitter only) -> repeat
& take min.  CP-SAT solve uses a tiny time_s (we only read info["precompute_wall"]).

Also runs window_tardy_only in {False (stress, all blocks active -- HANDOFF spec),
True (production -- only near-tardy active)} since bitmask builds _fp for ALL
placed blocks: it may HELP the saturated stress case but HURT the sparse prod case.

env: C:/Users/peter/anaconda3/envs/ogc2025/python.exe  (conda run 금지)
out: stdout + _bmbench.log
"""
import os, sys, json, time, traceback

SB = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(SB, "v7")
sys.path.insert(0, SB)
sys.path.insert(0, V7)   # v7 FIRST (dual-tree trap guard)

for k, v in dict(OGC_FIT="1", OGC_DIVERSE="1", OGC_CONTACT_D="2", OGC_WALL_W="1",
                 OGC_TOSS="0", OGC_PACK_SWAP="0", OGC_GUIDE_ATLOOSE="0", OGC_LNS="0",
                 OGC_MERGE="0", OGC_GLOBAL="1", OGC_ORDER="blend", OGC_ORDER_ALPHA="0.5",
                 OGC_FFT_MASK="1").items():
    os.environ.setdefault(k, v)
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass

import unified_greedy as UG                       # noqa: E402
from v3pp import adapter, seed as S, crane_cpsat as C   # noqa: E402

# dual-tree assert: must import the v7 tree, not parent/_m1base
assert "v7" in UG.__file__.replace("\\", "/"), UG.__file__
assert "v7" in C.__file__.replace("\\", "/"), C.__file__

BASE = "C:/claude-develop/OGC2026"
LOG = os.path.join(SB, "_bmbench.log")
INST = int(os.environ.get("BM_INST", "38"))
REPEAT = int(os.environ.get("BM_REPEAT", "3"))
SOLVE_TS = float(os.environ.get("BM_TS", "3"))     # tiny: we read precompute_wall only
NXCAND = int(os.environ.get("BM_NX", "5"))


def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s, flush=True)


ARMS = {
    "neither": dict(OGC_PRECOMP_AABB="0", OGC_PRECOMP_BITMASK="0"),
    "AABB   ": dict(OGC_PRECOMP_AABB="1", OGC_PRECOMP_BITMASK="0"),
    "AABB+BM": dict(OGC_PRECOMP_AABB="1", OGC_PRECOMP_BITMASK="1"),
    "BMonly ": dict(OGC_PRECOMP_AABB="0", OGC_PRECOMP_BITMASK="1"),
}


def run_bay(cur, j, wto):
    """One precompute+solve call; return info dict."""
    new_pl, st, wall, info = C.crane_repack_bay(
        data, j, cur[j], SOLVE_TS, n_xcand=NXCAND, window_tardy_only=wto)
    return info


def bench(cur, j, nblocks):
    for wto in (False, True):
        log(f"\n## window_tardy_only={wto}  (bay {j}, {nblocks} blocks, "
            f"n_xcand={NXCAND}, solve_ts={SOLVE_TS}s, repeat={REPEAT})")
        log(f"{'arm':<8} {'n_stored':>9} {'n_combos':>9} {'cands':>6} "
            f"{'pre_min':>8} {'pre_med':>8} {'cpsat':>7}")
        ref_stored = None
        for tag, env in ARMS.items():
            for k, v in env.items():
                os.environ[k] = v
            pcs, stored, combos, cands, cpsat = [], None, None, None, None
            for _ in range(REPEAT):
                info = run_bay(cur, j, wto)
                pcs.append(info["precompute_wall"])
                stored, combos = info["n_stored"], info["n_combos"]
                cands = info["n_cands_total"]
                cpsat = info.get("cpsat_wall", 0.0)
            pcs.sort()
            mn, md = pcs[0], pcs[len(pcs) // 2]
            flag = ""
            if ref_stored is None:
                ref_stored = stored
            elif stored != ref_stored:
                flag = f"  <<< STORED MISMATCH! ref={ref_stored}"
            log(f"{tag:<8} {stored:>9,} {combos:>9,} {cands:>6,} "
                f"{mn:>8.2f} {md:>8.2f} {cpsat:>7.2f}{flag}")


def main():
    global data
    log(f"\n\n# ===== BITMASK precompute bench  prob_{INST}  "
        f"{time.strftime('%Y-%m-%d %H:%M')} =====")
    log(f"# code: UG={UG.__file__}")
    path = f"{BASE}/instances/train/prob_{INST}.json"
    data = json.load(open(path, encoding="utf-8"))
    log(f"# greedy start (TL=70s) ...")
    UG._REGREEDY_PEN = {}
    t0 = time.time()
    res = UG.unified(data, 70.0, path)[0]
    sol0 = res["_solution"]
    cur = adapter.deserialize(data, sol0)
    log(f"# greedy done {time.time()-t0:.0f}s, obj={res.get('objective'):,.0f}")
    sizes = sorted(((len(pl), j) for j, pl in cur.items()), reverse=True)
    log(f"# bay sizes (top5): {sizes[:5]}")
    nblocks, j = sizes[0]
    log(f"# => biggest bay = {j} with {nblocks} blocks")
    try:
        bench(cur, j, nblocks)
    except Exception as e:
        log(f"# FAILED: {e!r}")
        traceback.print_exc()
    log(f"# ===== COMPLETE {time.strftime('%Y-%m-%d %H:%M')} =====")


if __name__ == "__main__":
    main()
