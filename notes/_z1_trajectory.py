import subprocess, sys, os, json
ROOT=os.getcwd()
insts=sys.argv[1].split(",") if len(sys.argv)>1 else ["prob_13","prob_14","prob_20"]
tl=sys.argv[2] if len(sys.argv)>2 else "300"
out={}
for inst in insts:
    env=dict(os.environ); env["OGC_STAGE_TIMING"]="1"
    cmd=[sys.executable,"tools/run_solver_once.py",f"instances/train/{inst}.json",
         "--solver","our","--timelimit",tl]
    p=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,timeout=float(tl)+600)
    timing=sobj=None; z1final=None
    for line in p.stdout.splitlines():
        if line.strip().startswith("{"):
            try: z1final=json.loads(line).get("obj1")
            except: pass
    for line in p.stderr.splitlines():
        if line.startswith("[STAGE_TIMING]"): timing=json.loads(line[14:])
        if line.startswith("[STAGE_OBJ]"): sobj=json.loads(line[11:])
    out[inst]={"timing":timing,"sobj":sobj,"z1final":z1final}
    print(f"done {inst} Z1final={z1final}",flush=True)
json.dump(out, open("results/z1_trajectory.json","w"), indent=1)
print("WROTE results/z1_trajectory.json")
