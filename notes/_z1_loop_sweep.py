"""Parallel Z1 sweep across instances. Usage:
  python notes/_z1_loop_sweep.py --timelimit 60 --conc 6 --tag triage \
      [--instances prob_1,prob_2,...] [--env OGC_X=1,OGC_Y=2]
Runs tools/run_solver_once.py per instance in subprocesses, concurrency-capped.
Writes results/z1_loop_<tag>.json and prints a table sorted by Z1 desc.
"""
import argparse, json, subprocess, sys, os, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent

def run_one(inst, tl, extra_env):
    env = dict(os.environ)
    env.update(extra_env)
    p = ROOT / "instances" / "train" / f"{inst}.json"
    t0 = time.time()
    try:
        out = subprocess.run(
            [sys.executable, str(ROOT/"tools"/"run_solver_once.py"), str(p),
             "--solver", "our", "--timelimit", str(tl)],
            capture_output=True, text=True, env=env, timeout=tl+120)
        line = [l for l in out.stdout.strip().splitlines() if l.startswith("{")]
        if not line:
            return {"inst": inst, "feas": False, "err": (out.stderr[-300:] or "no json"), "wall": time.time()-t0}
        d = json.loads(line[-1])
        return {"inst": inst, "feas": bool(d.get("feasible")),
                "Z1": d.get("obj1"), "Z2": d.get("obj2"), "Z3": d.get("obj3"),
                "obj": d.get("objective"), "elapsed": d.get("elapsed"),
                "stage": d.get("stage"), "err": d.get("error"),
                "wall": time.time()-t0}
    except subprocess.TimeoutExpired:
        return {"inst": inst, "feas": False, "err": "TIMEOUT", "wall": time.time()-t0}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timelimit", type=float, default=60)
    ap.add_argument("--conc", type=int, default=6)
    ap.add_argument("--tag", default="triage")
    ap.add_argument("--instances", default=",".join(f"prob_{i}" for i in range(1,21)))
    ap.add_argument("--env", default="")
    args = ap.parse_args()
    extra_env = {}
    if args.env:
        for kv in args.env.split(","):
            if "=" in kv:
                k,v = kv.split("=",1); extra_env[k]=v
    insts = args.instances.split(",")
    print(f"sweep tl={args.timelimit}s conc={args.conc} env={extra_env} n={len(insts)}", flush=True)
    results = {}
    with ThreadPoolExecutor(max_workers=args.conc) as ex:
        futs = {ex.submit(run_one, i, args.timelimit, extra_env): i for i in insts}
        for f in as_completed(futs):
            r = f.result()
            results[r["inst"]] = r
            z1 = r.get("Z1", r.get("z1"))
            print(f"  done {r['inst']:9s} feas={r.get('feas')} Z1={z1} wall={r.get('wall',0):.1f}", flush=True)
    out = ROOT/"results"/f"z1_loop_{args.tag}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n=== sorted by Z1 desc (tag={args.tag}) ===")
    def z1of(r): 
        v = r.get("Z1", r.get("z1"))
        return v if isinstance(v,(int,float)) else -1
    for inst, r in sorted(results.items(), key=lambda kv: -z1of(kv[1])):
        z1 = z1of(r)
        mark = "OK " if (isinstance(z1,(int,float)) and 0<=z1<20) else "!! "
        print(f"  {mark}{inst:9s} feas={r.get('feas')} Z1={z1} Z2={r.get('Z2')} Z3={r.get('Z3')} wall={r.get('wall',0):.1f}")
    print(f"WROTE {out}")

if __name__ == "__main__":
    main()
