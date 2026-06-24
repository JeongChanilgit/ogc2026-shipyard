import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
JOBS = [("prob_20", 60, "base@60=52258, full@60=1864"),
        ("prob_6", 600, "base@600=4, full@600=95")]
for inst, tl, ref in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    e = dict(os.environ); e.update({"OGC_FAST_FALLBACK": "1", "OGC_FAST_POS_TOP": "4"})
    p = subprocess.run([sys.executable, runner, instp, "--solver", "our",
                        "--timelimit", str(tl)], capture_output=True, text=True, env=e)
    line = ""
    for ln in reversed(p.stdout.strip().splitlines()):
        if ln.strip().startswith("{"): line = ln.strip(); break
    try: r = json.loads(line)
    except Exception: r = {"err": line[:120], "stderr": p.stderr[-200:]}
    print(f"{inst:9} fallback @{tl}s  feas={r.get('feasible')} Z1={r.get('obj1')} "
          f"obj={r.get('objective')} elapsed={r.get('elapsed')}  [refs: {ref}]")
    sys.stdout.flush()
