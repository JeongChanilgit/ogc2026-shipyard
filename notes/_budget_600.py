import subprocess,sys,os,json
ROOT=os.getcwd(); sys.path.insert(0,"tools"); import ogc_analysis as A
# (instance, timelimit, lever_reserve_pct, label)
runs=[("prob_20","600","22","600_default"),
      ("prob_20","600","45","600_morepost"),
      ("prob_13","600","22","600_default"),
      ("prob_14","600","22","600_default")]
for inst,tl,lr,lab in runs:
    env=dict(os.environ); env["OGC_STAGE_TIMING"]="1"; env["OGC_LEVER_RESERVE_PCT"]=lr
    out=f"results/_b600_{inst}_{lab}.json"
    cmd=[sys.executable,"tools/run_solver_once.py",f"instances/train/{inst}.json",
         "--solver","our","--timelimit",tl,"--save-sol",out]
    p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,timeout=float(tl)+600)
    sd=cl=None
    for line in p.stderr.splitlines():
        if line.startswith("[STAGE_TIMING]"):
            st=json.loads(line[14:])["stages"]; sd=st.get("seeds_decode"); cl=st.get("cum_level")
    prob=A.load_instance(inst); sol=A.load_solution(out)
    feas,obj,o1,o2,o3=A.obj_tuple(prob,sol)
    print(f"{inst} {lab} (lr={lr}): Z1={o1} Z2={o2} Z3={o3} feas={feas} | seeds={sd}s cum_level={cl}s",flush=True)
print("DONE",flush=True)
