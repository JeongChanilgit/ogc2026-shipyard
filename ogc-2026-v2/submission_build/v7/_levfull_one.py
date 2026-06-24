"""_score_one.py i tl outfile [cores] -- run the SUBMISSION's algorithm() on one
instance at TL, pin to `cores` (4-core affinity = faithful eval), eval with official
utils.check_feasibility, dump JSON result.

CRITICAL: all work is under `if __name__ == "__main__"`.  The submission spawns
multiprocessing workers (parcand/parallel_decode); on Windows spawn re-imports this
module, and WITHOUT the guard the children would re-run algorithm() (nested!).
"""
import json, time, os, sys

THIS = os.path.dirname(os.path.abspath(__file__))
if THIS not in sys.path:
    sys.path.insert(0, THIS)
BASE = "C:/claude-develop/OGC2026"


def run(i, tl, outf, cores):
    if cores:
        try:
            import psutil
            psutil.Process().cpu_affinity([int(c) for c in cores.split(",")])
            print(f"[affinity] prob_{i} pinned to {cores}", flush=True)
        except Exception as e:
            print(f"[affinity-FAIL] prob_{i}: {e}", flush=True)
    import myalgorithm, utils
    data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
    t0 = time.time()
    try:
        sol = myalgorithm.algorithm(data, tl)
        wall = time.time() - t0
        r = utils.check_feasibility(data, sol)
        obj = r.get("objective")
        res = {"i": i, "obj": obj, "z1": r.get("obj1"), "z2": r.get("obj2"),
               "z3": r.get("obj3"), "feas": obj is not None, "stage": r.get("stage"),
               "wall": round(wall, 1)}
    except Exception as e:
        import traceback
        res = {"i": i, "obj": None, "feas": False, "stage": "CRASH:" + type(e).__name__,
               "err": traceback.format_exc().splitlines()[-1], "wall": round(time.time() - t0, 1)}
    json.dump(res, open(outf, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"RESULT prob_{i}: obj={res.get('obj')} feas={res.get('feas')} wall={res.get('wall')}s", flush=True)


if __name__ == "__main__":
    i = int(sys.argv[1]); tl = float(sys.argv[2]); outf = sys.argv[3]
    cores = sys.argv[4] if len(sys.argv) > 4 else None
    run(i, tl, outf, cores)
