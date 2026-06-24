# -*- coding: utf-8 -*-
"""Z1 -> 0 campaign: FULL setup at 600s on the hard instances.
full = OGC_FAST_POSITIONS=1 + OGC_FAST_POS_TOP=4 (cache + bay-parallel default ON)."""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
ENV = {"OGC_FAST_POSITIONS": "1", "OGC_FAST_POS_TOP": "4"}
JOBS = [("prob_6", 600), ("prob_14", 600), ("prob_20", 600)]
# trajectory context from earlier runs (full): 60s / 300s
TRAJ = {"prob_6": {"60": 578, "300": 100}, "prob_14": {"60": 1804},
        "prob_20": {"60": 1864, "300": 416}}
rows = []
print(f"{'inst':9}{'tl':5}{'feas':6}{'objective':>15}{'Z1':>9}{'Z2':>8}{'Z3':>8}{'elapsed':>9}{'viol':>5}")
for inst, tl in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    e = dict(os.environ); e.update(ENV)
    cmd = [sys.executable, runner, instp, "--solver", "our", "--timelimit", str(tl)]
    p = subprocess.run(cmd, capture_output=True, text=True, env=e)
    line = ""
    for ln in reversed(p.stdout.strip().splitlines()):
        if ln.strip().startswith("{"):
            line = ln.strip(); break
    try: r = json.loads(line)
    except Exception: r = {"parse_error": line[:140], "stderr": p.stderr[-260:]}
    r.update({"inst": inst, "tl": tl})
    rows.append(r)
    print(f"{inst:9}{tl:<5}{str(r.get('feasible')):6}{str(r.get('objective')):>15}"
          f"{str(r.get('obj1')):>9}{str(r.get('obj2')):>8}{str(r.get('obj3')):>8}"
          f"{str(r.get('elapsed')):>9}{str(r.get('n_violations')):>5}")
    sys.stdout.flush()
print("\n=== Z1 trajectory (full): 60s -> 300s -> 600s ===")
for inst, _ in JOBS:
    r = next((x for x in rows if x["inst"] == inst), {})
    t = TRAJ.get(inst, {})
    print(f"  {inst:9} 60s={t.get('60')}  300s={t.get('300')}  600s={r.get('obj1')}  (feas={r.get('feasible')})")
(ROOT / "results" / "z1_drive0_600s.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nWROTE results/z1_drive0_600s.json")
