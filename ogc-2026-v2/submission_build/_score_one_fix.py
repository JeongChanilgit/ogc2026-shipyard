"""_score_one_fix.py i tl outfile [cores] -- run myalgorithm_fix on one instance,
capture _TRACE provenance (v1/v2 base, per-stage objs, postproc gain), eval official."""
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
        except Exception as e:
            print(f"[affinity-FAIL] prob_{i}: {e}", flush=True)
    import myalgorithm_fix as M, utils
    data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
    t0 = time.time()
    try:
        sol = M.algorithm(data, tl)
        wall = time.time() - t0
        r = utils.check_feasibility(data, sol)
        obj = r.get("objective")
        tr = dict(M._TRACE)
        res = {"i": i, "obj": obj, "z1": r.get("obj1"), "z2": r.get("obj2"),
               "z3": r.get("obj3"), "feas": obj is not None, "stage": r.get("stage"),
               "wall": round(wall, 1),
               "base": tr.get("base_src"), "base_obj": tr.get("base_obj"),
               "v2_obj": tr.get("v2_obj"), "orig_obj": tr.get("orig_obj"),
               "pp_obj": tr.get("pp_obj"), "pp_improved": bool(tr.get("pp_improved")),
               "v2_wall": tr.get("v2_wall"), "orig_wall": tr.get("orig_wall"),
               "pp_budget": tr.get("pp_budget"), "pp_wall": tr.get("pp_wall"),
               "final_src": tr.get("final_src")}
    except Exception as e:
        import traceback
        res = {"i": i, "obj": None, "feas": False, "stage": "CRASH:" + type(e).__name__,
               "err": traceback.format_exc().splitlines()[-1], "wall": round(time.time() - t0, 1)}
    json.dump(res, open(outf, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"RESULT prob_{i}: obj={res.get('obj')} base={res.get('base')} "
          f"pp_improved={res.get('pp_improved')} wall={res.get('wall')}s", flush=True)


if __name__ == "__main__":
    i = int(sys.argv[1]); tl = float(sys.argv[2]); outf = sys.argv[3]
    cores = sys.argv[4] if len(sys.argv) > 4 else None
    run(i, tl, outf, cores)
