import subprocess,sys,os,json
ROOT=os.getcwd(); sys.path.insert(0,"tools"); import ogc_analysis as A
for fold in ["0","1"]:
    env=dict(os.environ); env["OGC_STAGE_TIMING"]="1"; env["OGC_FOLD_SEEDS"]=fold
    out=f"results/_fold_{fold}.json"
    cmd=[sys.executable,"tools/run_solver_once.py","instances/train/prob_20.json",
         "--solver","our","--timelimit","300","--save-sol",out]
    p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,timeout=900)
    seeds_t=total=None
    for line in p.stderr.splitlines():
        if line.startswith("[STAGE_TIMING]"):
            d=json.loads(line[14:]); seeds_t=d["stages"].get("seeds_decode"); total=d["total_s"]
            search_t=d["stages"].get("search")
    prob=A.load_instance("prob_20"); sol=A.load_solution(out)
    feas,obj,o1,o2,o3=A.obj_tuple(prob,sol)
    print(f"FOLD={fold}: seeds_decode={seeds_t}s search={search_t}s total={total}s | Z1={o1} feas={feas}",flush=True)
print("DONE",flush=True)
