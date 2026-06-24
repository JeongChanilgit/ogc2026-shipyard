# -*- coding: utf-8 -*-
"""Validate OGC_FAST_POS_ADAPT (budget-aware fast positions).
prob_6@600s: ample budget -> should keep full search -> reach base@600s=4 (not full's 95).
prob_20@60s: tight budget -> should use fast -> keep full's 1864 (not base's 52258)."""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
JOBS = [
    ("prob_6", 600, {"OGC_FAST_POS_ADAPT": "1", "OGC_FAST_POS_TOP": "4"}, "adapt",
     "base@600=4, full@600=95"),
    ("prob_20", 60, {"OGC_FAST_POS_ADAPT": "1", "OGC_FAST_POS_TOP": "4"}, "adapt",
     "base@60=52258, full@60=1864"),
]
rows = []
for inst, tl, envadd, tag, ref in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    e = dict(os.environ); e.update(envadd)
    cmd = [sys.executable, runner, instp, "--solver", "our", "--timelimit", str(tl)]
    p = subprocess.run(cmd, capture_output=True, text=True, env=e)
    line = ""
    for ln in reversed(p.stdout.strip().splitlines()):
        if ln.strip().startswith("{"):
            line = ln.strip(); break
    try: r = json.loads(line)
    except Exception: r = {"parse_error": line[:140], "stderr": p.stderr[-260:]}
    r.update({"inst": inst, "tl": tl, "tag": tag, "ref": ref})
    rows.append(r)
    print(f"{inst:9} {tag} @{tl}s  feas={r.get('feasible')} obj={r.get('objective')} "
          f"Z1={r.get('obj1')} Z2={r.get('obj2')} Z3={r.get('obj3')} "
          f"elapsed={r.get('elapsed')}  [refs: {ref}]")
    sys.stdout.flush()
(ROOT / "results" / "z1_adapt_validate.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("WROTE results/z1_adapt_validate.json")
