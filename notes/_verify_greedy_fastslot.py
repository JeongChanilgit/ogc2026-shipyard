"""Byte-identical A/B for OGC_GREEDY_FAST_SLOT.  Read-only correctness gate.

For each instance, run the greedy baseline with the fast-slot path OFF vs ON under a
HUGE budget (so the time-based force-place guard never triggers -> pure geometric
output) and a FIXED PYTHONHASHSEED (so any non-determinism is neutralised).  The two
solutions MUST be byte-identical: that proves the precompute restructuring of
_find_earliest_slot changes nothing but speed.  Also times the greedy each way.

  python notes/_verify_greedy_fastslot.py --instances prob_1,...,prob_20 --concurrency 5
"""
import argparse, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "instances" / "train"
OUT = ROOT / "results" / "z1traj"
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
HUGE = 100000.0  # budget so big the greedy's 90%-timelimit force-place never fires

DRIVER = r'''
import json, time, sys, hashlib
sys.path.insert(0, "src")
from baseline_greedy import greedyalgorithm
prob = json.load(open(sys.argv[1], encoding="utf-8"))
budget = float(sys.argv[2]); out = sys.argv[3]
t0 = time.monotonic(); sol = greedyalgorithm(prob, budget); dt = time.monotonic() - t0
blob = json.dumps(sol, sort_keys=True, separators=(",", ":"))
h = hashlib.sha256(blob.encode()).hexdigest()
json.dump({"wall": round(dt, 3), "sha": h, "nops": len(sol.get("operations", {}))},
          open(out, "w"))
'''

def run(inst, fast):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["OGC_GREEDY_FAST_SLOT"] = "1" if fast else "0"
    tag = "on" if fast else "off"
    res = OUT / f"_vg_{inst}_{tag}.json"
    drv = OUT / f"_vg_driver.py"
    drv.write_text(DRIVER)
    if res.exists():
        res.unlink()
    try:
        subprocess.run([PYEXE, str(drv), str(TRAIN / f"{inst}.json"), str(HUGE), str(res)],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=900)
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"}
    if res.exists():
        try:
            return json.load(open(res))
        except Exception as e:
            return {"err": f"parse: {e}"}
    return {"err": "no result"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default=",".join(f"prob_{n}" for n in range(1, 21)))
    ap.add_argument("--concurrency", type=int, default=5)
    a = ap.parse_args()
    insts = [s.strip() for s in a.instances.split(",") if s.strip()]
    # run all (inst, off) and (inst, on) tasks
    tasks = [(i, f) for i in insts for f in (False, True)]
    out = {}
    with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
        futs = {ex.submit(run, i, f): (i, f) for i, f in tasks}
        for fu in futs:
            i, f = futs[fu]
            out[(i, f)] = fu.result()
    print(f"{'inst':9} | {'off wall':>9} {'on wall':>9} {'speedup':>8} | identical?")
    n_ident = n_diff = n_err = 0
    tot_off = tot_on = 0.0
    for i in insts:
        o = out.get((i, False), {}); n = out.get((i, True), {})
        if "err" in o or "err" in n:
            print(f"{i:9} | ERR off={o.get('err','-')} on={n.get('err','-')}")
            n_err += 1
            continue
        ident = (o["sha"] == n["sha"])
        sp = (o["wall"] / n["wall"]) if n["wall"] > 1e-9 else float("inf")
        tot_off += o["wall"]; tot_on += n["wall"]
        flag = "YES" if ident else "*** NO -- DIFFERS ***"
        print(f"{i:9} | {o['wall']:>9.2f} {n['wall']:>9.2f} {sp:>7.2f}x | {flag}")
        n_ident += ident; n_diff += (not ident)
    print("-" * 60)
    print(f"identical: {n_ident}/{len(insts)}   differs: {n_diff}   err: {n_err}")
    if tot_on > 1e-9:
        print(f"total greedy wall: off={tot_off:.1f}s  on={tot_on:.1f}s  "
              f"overall speedup={tot_off/tot_on:.2f}x")
    print("VERDICT:", "SAFE (byte-identical everywhere)" if n_diff == 0 and n_err == 0
          else "NOT SAFE -- investigate diffs")

if __name__ == "__main__":
    main()
