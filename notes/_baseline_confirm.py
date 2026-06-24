import subprocess, sys, os, json
ROOT=os.getcwd()
sys.path.insert(0,"tools"); import ogc_analysis as A
insts=["prob_11","prob_12","prob_13","prob_14","prob_15","prob_20"]
tl="300"
print(f"{'inst':9} {'Z1':>5} {'Z2':>6} {'Z3':>6} {'feas':>5}", flush=True)
for inst in insts:
    out=f"results/_base_{inst}.json"
    cmd=[sys.executable,"tools/run_solver_once.py",f"instances/train/{inst}.json",
         "--solver","our","--timelimit",tl,"--save-sol",out]
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=float(tl)+600)
    try:
        sol=A.load_solution(out); prob=A.load_instance(inst)
        feas,obj,o1,o2,o3=A.obj_tuple(prob,sol)
    except Exception as e: o1=o2=o3="ERR"; feas=str(e)[:15]
    print(f"{inst:9} {str(o1):>5} {str(o2):>6} {str(o3):>6} {str(feas):>5}", flush=True)
print("DONE",flush=True)
