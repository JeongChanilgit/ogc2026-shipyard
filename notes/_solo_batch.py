import subprocess, sys, os, json
ROOT = os.getcwd()
insts = sys.argv[1].split(",") if len(sys.argv)>1 else ["prob_6","prob_9","prob_11","prob_12","prob_13","prob_14","prob_15","prob_20"]
tl = sys.argv[2] if len(sys.argv)>2 else "300"
for inst in insts:
    out = f"results/_routed_{inst}.json"
    env = dict(os.environ); env["OGC_STAGE_TIMING"]="1"
    cmd = [sys.executable, "tools/run_solver_once.py", f"instances/train/{inst}.json",
           "--solver","our","--timelimit",tl,"--save-sol",out]
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=float(tl)+600)
    z1=None
    for line in reversed(p.stdout.strip().splitlines()):
        line=line.strip()
        if line.startswith("{"):
            try: z1=json.loads(line).get("obj1"); break
            except: pass
    # find which bays were routed to slab from stderr? print stage timing line
    st=""
    for line in p.stderr.splitlines():
        if line.startswith("[STAGE_TIMING]"): st=line[14:]
    print(f"{inst}: Z1={z1}  saved={out}", flush=True)
print("ALLDONE", flush=True)
