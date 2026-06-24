# -*- coding: utf-8 -*-
"""Full-solve @60s: does faster decode (OGC_FAST_POSITIONS) lower Z1 by avoiding
truncation/force-place?  Repeats each config to cope with run-to-run variance.
Run under ogc2025:  conda run -n ogc2025 python notes/_z1_fastpos.py"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
CONFIGS = {
    "base":        {},
    "fastpos":     {"OGC_FAST_POSITIONS": "1"},
    "fastpos+ee":  {"OGC_FAST_POSITIONS": "1", "OGC_DECODE_EARLY_EXIT": "1"},
}
JOBS = [("prob_6", 60), ("prob_14", 60)]
REPEATS = 2

rows = []
print(f"{'inst':9}{'cfg':12}{'run':4}{'feas':6}{'objective':>14}{'Z1':>9}{'elapsed':>9}{'viol':>6}")
for inst, tl in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    for cfg, envadd in CONFIGS.items():
        for run in range(REPEATS):
            e = dict(os.environ); e.update(envadd)
            cmd = [sys.executable, runner, instp, "--solver", "our", "--timelimit", str(tl)]
            p = subprocess.run(cmd, capture_output=True, text=True, env=e)
            line = ""
            for ln in reversed(p.stdout.strip().splitlines()):
                if ln.strip().startswith("{"):
                    line = ln.strip(); break
            try: r = json.loads(line)
            except Exception: r = {"parse_error": line[:140], "stderr": p.stderr[-260:]}
            r["cfg"] = cfg; r["run"] = run; r["inst"] = inst
            rows.append(r)
            print(f"{inst:9}{cfg:12}{run:<4}{str(r.get('feasible')):6}"
                  f"{str(r.get('objective')):>14}{str(r.get('obj1')):>9}"
                  f"{str(r.get('elapsed')):>9}{str(r.get('n_violations')):>6}")
            sys.stdout.flush()

print("\n=== Z1 summary (min over runs; lower=better) ===")
by = {}
for r in rows:
    by.setdefault((r.get("inst"), r["cfg"]), []).append(r)
for inst, _ in JOBS:
    base_z = [x.get("obj1") for x in by.get((inst, "base"), []) if x.get("obj1") is not None]
    bmin = min(base_z) if base_z else None
    line = f"  {inst:9} base.Z1min={bmin}"
    for cfg in ("fastpos", "fastpos+ee"):
        zs = [x.get("obj1") for x in by.get((inst, cfg), []) if x.get("obj1") is not None]
        feas = all(x.get("feasible") for x in by.get((inst, cfg), []))
        line += f"  {cfg}.Z1min={min(zs) if zs else None}(feas={feas})"
    print(line)

(ROOT / "results").mkdir(exist_ok=True)
(ROOT / "results" / "z1_fastpos.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nWROTE results/z1_fastpos.json")
