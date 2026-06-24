"""_v5_one.py i tl outfile cores [MODE]  -- run v5 (or current) on one instance,
save metrics + full solution (for 3D). MODE=v5(default)|cur."""
import sys, os, json, time

V5 = os.path.dirname(os.path.abspath(__file__))
SB = r"C:/claude-develop/OGC2026/ogc-2026-v2/submission_build"
for p in (V5, SB):
    if p not in sys.path:
        sys.path.insert(0, p)
BASE = "C:/claude-develop/OGC2026"


def run(i, tl, outf, cores, mode):
    if cores:
        try:
            import psutil
            psutil.Process().cpu_affinity([int(c) for c in cores.split(",")])
        except Exception as e:
            print(f"[aff-fail] {e}", flush=True)
    import utils
    data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
    t0 = time.time()
    if mode == "cur":
        os.environ.setdefault("OGC_NO_V1", "1")
        os.environ.setdefault("OGC_PLACE_W1_SCALE", "0.5")
        os.environ.setdefault("OGC_TOSS", "1")
        os.environ.setdefault("OGC_FIXOPT", "1")
        os.environ.setdefault("OGC_PP_MOVEALL", "1")
        os.environ.setdefault("OGC_V2_CAP", "110")
        import myalgorithm_fix as M
        sol = M.algorithm(data, tl)
    else:
        import v5_solver as V
        sol = V.algorithm(data, tl)
    wall = time.time() - t0
    r = utils.check_feasibility(data, sol)
    res = {"i": i, "mode": mode, "obj": r.get("objective"), "z1": r.get("obj1"),
           "z2": r.get("obj2"), "z3": r.get("obj3"),
           "feas": r.get("objective") is not None, "wall": round(wall, 1),
           "sol": sol}
    json.dump(res, open(outf, "w", encoding="utf-8"))
    print(f"RESULT prob_{i} [{mode}]: obj={res['obj']} z1={res['z1']} z3={res['z3']} "
          f"feas={res['feas']} wall={res['wall']}s", flush=True)


if __name__ == "__main__":
    i = int(sys.argv[1]); tl = float(sys.argv[2]); outf = sys.argv[3]
    cores = sys.argv[4] if len(sys.argv) > 4 else None
    mode = sys.argv[5] if len(sys.argv) > 5 else "v5"
    run(i, tl, outf, cores, mode)
