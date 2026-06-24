"""Held-out generalization A/B: levers OFF vs ON on never-seen instances.
  python notes/_z1_holdout_ab.py --timelimit 300 --conc 6
Runs each instances/holdout/*.json with baseline (no env) and with the locked
lever config, reports Z1_off vs Z1_on. Lower Z1_on on unseen data => general.
"""
import argparse, json, subprocess, sys, os, time, glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
LEVER_ENV = {"OGC_CPSAT_TIMING":"1","OGC_CUMLEVEL":"1","OGC_CUMLEVEL_ORDERS":"3","OGC_CUMLEVEL_ALPHAS":"90;85;80"}

def run_one(path, tl, env_extra, tag):
    env = dict(os.environ); env.update(env_extra)
    try:
        out = subprocess.run([sys.executable, str(ROOT/"tools"/"run_solver_once.py"), str(path),
                              "--solver","our","--timelimit",str(tl)],
                             capture_output=True, text=True, env=env, timeout=tl+120)
        line=[l for l in out.stdout.strip().splitlines() if l.startswith("{")]
        d=json.loads(line[-1]) if line else {}
        return {"inst":Path(path).stem,"tag":tag,"feas":d.get("feasible"),"Z1":d.get("obj1"),
                "obj":d.get("objective")}
    except Exception as e:
        return {"inst":Path(path).stem,"tag":tag,"feas":False,"err":str(e)[:120]}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--timelimit",type=float,default=300); ap.add_argument("--conc",type=int,default=6)
    a=ap.parse_args()
    insts=sorted(glob.glob(str(ROOT/"instances"/"holdout"/"*.json")))
    jobs=[]
    for p in insts:
        jobs.append((p,{}, "OFF"))
        jobs.append((p,LEVER_ENV,"ON"))
    print(f"holdout A/B tl={a.timelimit} conc={a.conc} insts={[Path(p).stem for p in insts]}", flush=True)
    res={}
    with ThreadPoolExecutor(max_workers=a.conc) as ex:
        futs={ex.submit(run_one,p,a.timelimit,e,t):(Path(p).stem,t) for p,e,t in jobs}
        for f in as_completed(futs):
            r=f.result(); res[(r["inst"],r["tag"])]=r
            print(f"  {r['inst']:8s} {r['tag']:3s} feas={r.get('feas')} Z1={r.get('Z1')}", flush=True)
    print("\n=== held-out generalization (Z1 OFF vs ON) ===")
    for inst in sorted({k[0] for k in res}):
        off=res.get((inst,"OFF"),{}); on=res.get((inst,"ON"),{})
        zo,zn=off.get("Z1"),on.get("Z1")
        d = (zn-zo) if (isinstance(zo,(int,float)) and isinstance(zn,(int,float))) else "?"
        print(f"  {inst:8s} OFF={zo} ON={zn} delta={d}  {'GENERAL✓' if isinstance(d,(int,float)) and d<0 else ''}")
    Path(ROOT/"results"/"z1_holdout_ab.json").write_text(json.dumps({f'{k[0]}_{k[1]}':v for k,v in res.items()},indent=2),encoding="utf-8")

if __name__=="__main__": main()
