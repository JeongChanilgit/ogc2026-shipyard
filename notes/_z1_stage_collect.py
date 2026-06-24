"""Run all 20 instances with OGC_STAGE_TIMING=1, parse the [STAGE_TIMING] JSON line
from stderr, aggregate into results/stage_timing.json.  conc gives each instance a
clean 4-core slice on a 20-core box (eval-representative)."""
import json, subprocess, sys, os, re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
TL = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 4

def run(inst):
    env = dict(os.environ); env["OGC_STAGE_TIMING"] = "1"
    p = ROOT/"instances"/"train"/f"{inst}.json"
    try:
        out = subprocess.run([sys.executable, str(ROOT/"tools"/"run_solver_once.py"),
                              str(p), "--solver", "our", "--timelimit", str(TL)],
                             capture_output=True, text=True, env=env, timeout=TL+180)
        st = None
        for line in out.stderr.splitlines():
            if line.startswith("[STAGE_TIMING]"):
                st = json.loads(line[len("[STAGE_TIMING]"):])
        res = None
        for line in out.stdout.splitlines():
            if line.startswith("{"):
                res = json.loads(line)
        z1 = res.get("obj1") if res else None
        feas = res.get("feasible") if res else None
        elapsed = res.get("elapsed") if res else None
        if st is not None:
            st["Z1"] = z1; st["feasible"] = feas; st["elapsed_total"] = elapsed
        return inst, st
    except Exception as e:
        return inst, {"error": str(e)[:200]}

insts = [f"prob_{i}" for i in range(1, 21)]
print(f"collecting stage timing tl={TL}s conc={CONC} ({len(insts)} instances)", flush=True)
data = {}
with ThreadPoolExecutor(max_workers=CONC) as ex:
    futs = {ex.submit(run, i): i for i in insts}
    for f in as_completed(futs):
        inst, st = f.result()
        data[inst] = st
        if st and "stages" in st:
            print(f"  {inst:9s} Z1={st.get('Z1')} total={st.get('total_s')}s "
                  f"stages={ {k:round(v,1) for k,v in st['stages'].items()} }", flush=True)
        else:
            print(f"  {inst:9s} {st}", flush=True)
out = ROOT/"results"/"stage_timing.json"
out.write_text(json.dumps(data, indent=2), encoding="utf-8")
print(f"WROTE {out}")
