# -*- coding: utf-8 -*-
"""Does FAST_POSITIONS cap the achievable Z1 (ceiling) at a longer budget?
Compares base vs full at 300s on prob_6 (base@300s ref=76, @600s=4) and prob_20
(base@600s ref=360).  Run: conda run -n ogc2025 python notes/_z1_ceiling.py"""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
CONFIGS = {"base": {}, "full": {"OGC_FAST_POSITIONS": "1", "OGC_FAST_POS_TOP": "4"}}
JOBS = [("prob_6", 300), ("prob_20", 300)]
REF = {"prob_6": {"300": 76.0, "600": 4.0}, "prob_20": {"600": 360.0}}

rows = []
print(f"{'inst':9}{'cfg':6}{'tl':5}{'feas':6}{'objective':>15}{'Z1':>9}{'elapsed':>9}{'viol':>5}")
for inst, tl in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    for cfg, envadd in CONFIGS.items():
        e = dict(os.environ); e.update(envadd)
        cmd = [sys.executable, runner, instp, "--solver", "our", "--timelimit", str(tl)]
        p = subprocess.run(cmd, capture_output=True, text=True, env=e)
        line = ""
        for ln in reversed(p.stdout.strip().splitlines()):
            if ln.strip().startswith("{"):
                line = ln.strip(); break
        try: r = json.loads(line)
        except Exception: r = {"parse_error": line[:140], "stderr": p.stderr[-260:]}
        r.update({"cfg": cfg, "inst": inst, "tl": tl})
        rows.append(r)
        print(f"{inst:9}{cfg:6}{tl:<5}{str(r.get('feasible')):6}"
              f"{str(r.get('objective')):>15}{str(r.get('obj1')):>9}"
              f"{str(r.get('elapsed')):>9}{str(r.get('n_violations')):>5}")
        sys.stdout.flush()

print("\n=== CEILING: full@300s vs base@300s and known refs ===")
by = {(r["inst"], r["cfg"]): r for r in rows}
for inst, tl in JOBS:
    b = by.get((inst, "base"), {}).get("obj1")
    f = by.get((inst, "full"), {}).get("obj1")
    print(f"  {inst:9} base@{tl}s.Z1={b}  full@{tl}s.Z1={f}  refs={REF.get(inst)}")

(ROOT / "results" / "z1_ceiling_300s.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nWROTE results/z1_ceiling_300s.json")
