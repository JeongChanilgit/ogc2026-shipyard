# -*- coding: utf-8 -*-
"""Time sweep with FULL setup (FAST_POSITIONS TOP=4): how do Z1/Z2/Z3/objective
improve per minute up to 5 min?  Each budget is a separate anytime run."""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
ENV = {"OGC_FAST_POSITIONS": "1", "OGC_FAST_POS_TOP": "4"}
INSTS = ["prob_14", "prob_20"]
BUDGETS = [60, 120, 180, 240, 300]
rows = []
print(f"{'inst':9}{'tl':5}{'feas':6}{'Z1':>9}{'Z2':>8}{'Z3':>8}{'objective':>16}{'elapsed':>9}")
for inst in INSTS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    for tl in BUDGETS:
        e = dict(os.environ); e.update(ENV)
        p = subprocess.run([sys.executable, runner, instp, "--solver", "our",
                            "--timelimit", str(tl)], capture_output=True, text=True, env=e)
        line = ""
        for ln in reversed(p.stdout.strip().splitlines()):
            if ln.strip().startswith("{"): line = ln.strip(); break
        try: r = json.loads(line)
        except Exception: r = {"err": line[:120]}
        r.update({"inst": inst, "tl": tl})
        rows.append(r)
        print(f"{inst:9}{tl:<5}{str(r.get('feasible')):6}{str(r.get('obj1')):>9}"
              f"{str(r.get('obj2')):>8}{str(r.get('obj3')):>8}{str(r.get('objective')):>16}"
              f"{str(r.get('elapsed')):>9}")
        sys.stdout.flush()

print("\n=== Z1 trajectory per minute (full setup) ===")
by = {}
for r in rows: by.setdefault(r["inst"], {})[r["tl"]] = r
for inst in INSTS:
    traj = "  ".join(f"{tl//60}m={by[inst].get(tl,{}).get('obj1')}" for tl in BUDGETS)
    print(f"  {inst:9} Z1:  {traj}")
print()
for inst in INSTS:
    traj = "  ".join(f"{tl//60}m={by[inst].get(tl,{}).get('objective')}" for tl in BUDGETS)
    print(f"  {inst:9} obj: {traj}")
(ROOT / "results" / "z1_timesweep_full.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nWROTE results/z1_timesweep_full.json")
