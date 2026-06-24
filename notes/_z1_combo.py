# -*- coding: utf-8 -*-
"""Can the structural Z1 levers (CP-SAT seed + multi-reschedule) break the
full-only plateau (prob_14~309, prob_20~422 @300s) toward two digits?"""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
CONFIGS = {
    "full":      {"OGC_FAST_POSITIONS": "1", "OGC_FAST_POS_TOP": "4"},
    "full+struct": {"OGC_FAST_POSITIONS": "1", "OGC_FAST_POS_TOP": "4",
                    "OGC_CPSAT_FIRST": "1", "OGC_Z1_PUSH": "1"},
}
JOBS = [("prob_14", 300), ("prob_20", 300)]
rows = []
print(f"{'inst':9}{'cfg':12}{'feas':6}{'Z1':>9}{'Z2':>8}{'Z3':>8}{'objective':>16}{'elapsed':>9}")
for inst, tl in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    for cfg, envadd in CONFIGS.items():
        e = dict(os.environ); e.update(envadd)
        p = subprocess.run([sys.executable, runner, instp, "--solver", "our",
                            "--timelimit", str(tl)], capture_output=True, text=True, env=e)
        line = ""
        for ln in reversed(p.stdout.strip().splitlines()):
            if ln.strip().startswith("{"): line = ln.strip(); break
        try: r = json.loads(line)
        except Exception: r = {"err": line[:120]}
        r.update({"inst": inst, "cfg": cfg, "tl": tl})
        rows.append(r)
        print(f"{inst:9}{cfg:12}{str(r.get('feasible')):6}{str(r.get('obj1')):>9}"
              f"{str(r.get('obj2')):>8}{str(r.get('obj3')):>8}{str(r.get('objective')):>16}"
              f"{str(r.get('elapsed')):>9}")
        sys.stdout.flush()
print("\n=== struct vs full @300s (Z1) ===")
by = {(r["inst"], r["cfg"]): r for r in rows}
for inst, _ in JOBS:
    f = by.get((inst, "full"), {}).get("obj1")
    s = by.get((inst, "full+struct"), {}).get("obj1")
    print(f"  {inst:9} full.Z1={f}  full+struct.Z1={s}")
(ROOT / "results" / "z1_combo_300s.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("WROTE results/z1_combo_300s.json")
