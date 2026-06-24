import subprocess, sys, os, json
ROOT=os.getcwd()
sys.path.insert(0,"tools"); import ogc_analysis as A
runs=[("prob_13","0"),("prob_13","0"),("prob_13","1"),("prob_13","1"),
      ("prob_20","0"),("prob_20","0"),("prob_20","1"),("prob_20","1")]
tl="150"
print(f"{'inst':9} {'slab':>5} {'Z1':>6} {'feas':>5}", flush=True)
for i,(inst,slab) in enumerate(runs):
    out=f"results/_var_{inst}_{slab}_{i}.json"
    env=dict(os.environ); env["OGC_SLAB_PACK"]=slab
    cmd=[sys.executable,"tools/run_solver_once.py",f"instances/train/{inst}.json",
         "--solver","our","--timelimit",tl,"--save-sol",out]
    p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,timeout=float(tl)+600)
    prob=A.load_instance(inst); 
    try:
        sol=A.load_solution(out); feas,obj,o1,o2,o3=A.obj_tuple(prob,sol)
    except Exception as e:
        o1="ERR"; feas=str(e)[:20]
    cfg="ON" if slab=="1" else "OFF"
    print(f"{inst:9} {cfg:>5} {str(o1):>6} {str(feas):>5}", flush=True)
print("ALLDONE",flush=True)
