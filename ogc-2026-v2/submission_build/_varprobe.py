"""_varprobe.py -- prove the full-set cap20 'catastrophe' is BASE-SOLVER variance,
not a cap effect.  Runs v7 myalgorithm with postproc OFF (OGC_NO_PP=1 -> pure
best-of(v2,orig) base, cap-independent) N times on the catastrophe instances, plus
a couple controls.  If the BASE obj swings 5-10x run-to-run, the cap is exonerated
(it only touches postproc, which is never-worse).

Single 4-core slot, sequential.  out: stdout.
"""
import os, sys, json, time
THIS = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(THIS, "v7")
sys.path.insert(0, V7)
os.chdir(V7)
os.environ["OGC_NO_PP"] = "1"          # postproc OFF -> measure pure base
try:
    import psutil; psutil.Process().cpu_affinity([0, 1, 2, 3])
except Exception:
    pass
import myalgorithm, utils               # noqa: E402
BASE = "C:/claude-develop/OGC2026"
PROBS = [int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "25,27,38,30").split(",")]
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
TL = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0


def run(i):
    data = json.load(open(f"{BASE}/instances/train/prob_{i}.json", encoding="utf-8"))
    t = time.time()
    sol = myalgorithm.algorithm(data, TL)
    r = utils.check_feasibility(data, sol)
    return r.get("objective"), r.get("obj1"), time.time() - t


def main():
    print(f"# BASE variance probe (postproc OFF) TL={TL:.0f} reps={REPS}", flush=True)
    print(f"{'inst':>8} " + " ".join(f"run{k+1:>1}" .rjust(14) for k in range(REPS)) +
          f"  {'min':>14} {'max':>14} {'max/min':>8}", flush=True)
    for i in PROBS:
        objs = []
        for k in range(REPS):
            o, z1, w = run(i)
            objs.append(o)
            print(f"  prob_{i} run{k+1}: obj={o:,.0f} z1={z1} wall={w:.0f}s", flush=True)
        vals = [o for o in objs if o]
        if vals:
            mn, mx = min(vals), max(vals)
            ratio = mx / mn if mn else 0
            print(f">>> prob_{i}: min={mn:,.0f} max={mx:,.0f} max/min={ratio:.2f}x", flush=True)
    print("# DONE", flush=True)


if __name__ == "__main__":
    main()
