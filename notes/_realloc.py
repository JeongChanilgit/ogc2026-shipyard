import subprocess,sys,os,json
ROOT=os.getcwd(); sys.path.insert(0,"tools"); import ogc_analysis as A
# (lever_reserve_pct, max_pct, label) -- prob_20 @300s
cfgs=[("22","40","default"),("40","50","mid"),("68","75","aggr_front60")]
print(f"{'cfg':14} {'Z1':>5} {'front_s':>8} {'back_s':>7} {'cum_level':>9} {'seeds':>7}",flush=True)
for lr,mx,lab in cfgs:
    env=dict(os.environ); env["OGC_STAGE_TIMING"]="1"; env["OGC_LEVER_DEBUG"]="1"
    env["OGC_LEVER_RESERVE_PCT"]=lr; env["OGC_LEVER_RESERVE_MAX_PCT"]=mx
    out=f"results/_rl_{lab}.json"
    cmd=[sys.executable,"tools/run_solver_once.py","instances/train/prob_20.json",
         "--solver","our","--timelimit","300","--save-sol",out]
    p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,timeout=900)
    front=back=sd=cl=None
    for line in p.stderr.splitlines():
        if "[LEVERDBG]" in line:
            import re
            mm=re.search(r"decode_deadline=([\d.]+).*reserve_window=([\d.]+)",line)
            if mm: front=float(mm.group(1)); back=float(mm.group(2))
        if line.startswith("[STAGE_TIMING]"):
            st=json.loads(line[14:])["stages"]; sd=st.get("seeds_decode"); cl=st.get("cum_level")
    prob=A.load_instance("prob_20"); sol=A.load_solution(out)
    feas,obj,o1,o2,o3=A.obj_tuple(prob,sol)
    print(f"{lab:14} {str(o1):>5} {str(front):>8} {str(back):>7} {str(cl):>9} {str(sd):>7}",flush=True)
print("DONE",flush=True)
