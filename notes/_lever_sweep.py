"""Toggleable Z1-quality-lever sweep.  Read-only.  Each named config = submission
default + ONE hypothesis flag (or a combo), so we can see which lever lowers Z1 on
the stuck instances WITHOUT touching the default path.  SEQUENTIAL (no PARALLEL).

All configs include OGC_EXIT_ON_Z1_ZERO=1 (safe, faster) so reaching 0 returns early.

  python notes/_lever_sweep.py --instances prob_4,prob_13,prob_16,prob_9,prob_15 \
        --configs base,slab,z1push,atcr,orders5,dueforce --timelimit 300 --concurrency 3
"""
import argparse, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

EXIT = {"OGC_EXIT_ON_Z1_ZERO": "1"}
# Each config: hypothesis -> extra env flags (on top of EXIT + submission default).
CONFIGS = {
    "base":      {},                                                   # submission default
    "slab":      {"OGC_SLAB_PACK": "1"},                               # bbox slab-packing variant
    "z1push":    {"OGC_Z1_PUSH": "1"},                                 # insight (1): multi-order reschedule + LB-skip
    "atcr":      {"OGC_ATCR_SEED": "1"},                               # insight (8): ATC dispatch order
    "m4cut":     {"OGC_M4_CUT": "1"},                                  # insight (4): LBBD no-good cut
    "orders5":   {"OGC_CUMLEVEL_ORDERS": "5",
                  "OGC_CUMLEVEL_ALPHAS": "95;90;85;80;75"},            # wider cum_level best-of
    "dueforce":  {"OGC_DUE_FORCE": "1"},                               # single-move tardy bay reassign (any n)
    "xbaymoves": {"OGC_XBAY_MOVES": "80"},                             # deeper cross-bay relocation
    "combo":     {"OGC_SLAB_PACK": "1", "OGC_Z1_PUSH": "1",
                  "OGC_CUMLEVEL_ORDERS": "5"},                         # stack the promising ones
    "bestof":    {"OGC_SLAB_BESTOF": "1"},                            # slab default ON + true best-of (no mis-route regress)
    "treassign": {"OGC_TEMPORAL_REASSIGN": "1"},                      # Z-A: CP-SAT assignment+area-cumulative reassign (shelved; retest on oversubscribed)
    "treas_bof": {"OGC_TEMPORAL_REASSIGN": "1", "OGC_SLAB_BESTOF": "1"},  # Z-A + best-of packing
    "xbatch":    {"OGC_XBAY_BATCH": "1"},                             # batch bay-clearing LNS (accumulate through non-improving), default OFF
    "xbat_mv":   {"OGC_XBAY_BATCH": "1", "OGC_XBAY_MOVES": "80"},     # batch + deeper one-block relocate
    "xcands3":   {"OGC_XBAY_CANDS": "3"},                             # more target-bay candidates per relocate
    "xbat_c3":   {"OGC_XBAY_BATCH": "1", "OGC_XBAY_CANDS": "3"},      # batch + wider target search
    # --- z1<10 attack on prob_13/20 (2026-06-08) ---
    "tardyK":    {"OGC_TARDY_RELOC_K": "20"},                          # try relocating MANY tardy blocks (not just 8)
    "orders5":   {"OGC_CUMLEVEL_ORDERS": "5",
                  "OGC_CUMLEVEL_ALPHAS": "95;90;85;80;75"},            # wider cum_level best-of (overrides dup above is fine)
    "ord_tardy": {"OGC_CUMLEVEL_ORDERS": "5", "OGC_CUMLEVEL_ALPHAS": "95;90;85;80;75",
                  "OGC_TARDY_RELOC_K": "20"},                          # wider cum_level + deep tardy reloc
    "xbat_tardy":{"OGC_XBAY_BATCH": "1", "OGC_XBAY_MOVES": "80",
                  "OGC_TARDY_RELOC_K": "20"},                          # batch clearing + deep tardy reloc
    "cl_long":   {"OGC_CUMLEVEL_BUDGET_PCT": "85"},                    # give cum_level more of the window
}

DRIVER = r'''
import json, time, sys
sys.path.insert(0, "src"); sys.path.insert(0, "tools")
from myalgorithm import algorithm
import ogc_analysis as A
prob = json.load(open(sys.argv[1], encoding="utf-8"))
t0 = time.monotonic(); sol = algorithm(prob, float(sys.argv[2])); dt = time.monotonic()-t0
feas, obj, o1, o2, o3 = A.obj_tuple(prob, sol)
json.dump({"wall": round(dt,2), "feas": bool(feas), "z1": o1, "z2": o2, "z3": o3,
           "obj": obj}, open(sys.argv[3], "w"))
'''

def run(inst, cfg, tl):
    env = dict(os.environ); env.update(EXIT); env.update(CONFIGS[cfg])
    res = OUT / f"_ls_{inst}_{cfg}.json"
    drv = OUT / "_ls_driver.py"; drv.write_text(DRIVER)
    if res.exists(): res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN/f"{inst}.json"), str(tl), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=tl+150)
    except Exception as e:
        return inst, cfg, {"err": f"{type(e).__name__}"}
    if res.exists():
        try: return inst, cfg, json.load(open(res))
        except Exception: return inst, cfg, {"err": "parse"}
    return inst, cfg, {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", required=True)
    ap.add_argument("--configs", default="base,slab,z1push,atcr,orders5,dueforce")
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--concurrency", type=int, default=3)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    cfgs = [s.strip() for s in a.configs.split(",") if s.strip()]
    bad = [c for c in cfgs if c not in CONFIGS]
    if bad:
        print("unknown configs:", bad, "known:", list(CONFIGS)); return
    tasks = [(i, c) for i in insts for c in cfgs]
    res = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = [ex.submit(run, i, c, a.timelimit) for i, c in tasks]
        for f in futs:
            i, c, r = f.result(); res[(i, c)] = r
            zz = r.get("z1", r.get("err"))
            print(f"[done] {i:9} {c:10} z1={zz}", flush=True)
    print("\n=== Z1-lever sweep (z1 per config; lower=better) ===")
    hdr = "{:9}".format("inst")
    for c in cfgs: hdr += " | {:>9}".format(c)
    print(hdr)
    for i in insts:
        row = "{:9}".format(i)
        bz = res.get((i, "base"), {}).get("z1")
        for c in cfgs:
            r = res.get((i, c), {})
            if "err" in r: row += " | {:>9}".format("ERR")
            else:
                z = r["z1"]
                mark = ""
                if c != "base" and bz is not None and z is not None:
                    if z < bz - 1e-9: mark = "*"      # improved vs base
                    elif z > bz + 1e-9: mark = "x"     # regressed
                row += " | {:>8.0f}{}".format(z, mark)
        print(row)
    print("\n* = base보다 z1 개선,  x = 회귀")

if __name__ == "__main__":
    main()
