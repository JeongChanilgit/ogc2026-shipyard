# -*- coding: utf-8 -*-
"""Hypothesis test: does FULL decode-speed setup @60s reach baseline @600s quality?
full = OGC_FAST_POSITIONS=1 + OGC_FAST_POS_TOP=4 (aabb-cache + bay-parallel are
default ON).  Compares against known baseline @600s references.
Run under ogc2025:  conda run -n ogc2025 python notes/_z1_fullset.py"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
CONFIGS = {
    "base":  {},
    "full":  {"OGC_FAST_POSITIONS": "1", "OGC_FAST_POS_TOP": "4"},
}
JOBS = [("prob_6", 60), ("prob_14", 60), ("prob_20", 60)]
REPEATS = 2
# known baseline references at long budgets (from results/tlsweep_*, tl600_*)
REF600 = {"prob_6": 4.0, "prob_20": 360.0}      # baseline Z1 @600s
REF300 = {"prob_6": 76.0}

rows = []
print(f"{'inst':9}{'cfg':6}{'run':4}{'feas':6}{'objective':>15}{'Z1':>9}{'elapsed':>9}{'viol':>5}")
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
            r.update({"cfg": cfg, "run": run, "inst": inst})
            rows.append(r)
            print(f"{inst:9}{cfg:6}{run:<4}{str(r.get('feasible')):6}"
                  f"{str(r.get('objective')):>15}{str(r.get('obj1')):>9}"
                  f"{str(r.get('elapsed')):>9}{str(r.get('n_violations')):>5}")
            sys.stdout.flush()

print("\n=== HYPOTHESIS: full@60s  vs  baseline@600s(ref) ===")
by = {}
for r in rows:
    by.setdefault((r["inst"], r["cfg"]), []).append(r)
for inst, _ in JOBS:
    def zmin(cfg):
        zs = [x.get("obj1") for x in by.get((inst, cfg), []) if x.get("obj1") is not None]
        return min(zs) if zs else None
    b60, f60 = zmin("base"), zmin("full")
    ref = REF600.get(inst)
    feas = all(x.get("feasible") for x in by.get((inst, "full"), []))
    verdict = ""
    if ref is not None and f60 is not None:
        verdict = f"  -> full@60s/{ref}=ref600 : {'MATCHES~' if f60 <= ref*2 else 'above'} (ratio {f60/ref:.1f}x)"
    print(f"  {inst:9} base@60s.Z1={b60}  full@60s.Z1={f60}(feas={feas})  "
          f"baseline@600s.ref={ref}{verdict}")

(ROOT / "results").mkdir(exist_ok=True)
(ROOT / "results" / "z1_fullset_60s.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nWROTE results/z1_fullset_60s.json")
