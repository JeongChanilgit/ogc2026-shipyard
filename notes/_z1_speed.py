# -*- coding: utf-8 -*-
"""Time-efficiency experiment: does capping crane-check candidates (OGC_CAND_CAP)
reach LOWER Z1 in the SAME wall budget?  Also guards small instances.
Run under ogc2025:  conda run -n ogc2025 python notes/_z1_speed.py"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")

# base = default adaptive; cap = force cap 48 on bays >= 20 blocks (medium bays too)
CONFIGS = {
    "base":    {},
    "cap48":   {"OGC_CAND_CAP": "48", "OGC_CAND_CAP_MIN": "20"},
    "cap64":   {"OGC_CAND_CAP": "64", "OGC_CAND_CAP_MIN": "20"},
}
JOBS = [("prob_6", 120), ("prob_14", 120), ("prob_5", 60), ("prob_8", 60)]

rows = []
print(f"{'inst':9}{'cfg':8}{'feas':6}{'objective':>14}{'Z1':>9}{'Z2':>8}{'Z3':>8}{'elapsed':>9}{'viol':>6}")
for inst, tl in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    for cfg, envadd in CONFIGS.items():
        e = dict(os.environ); e.update(envadd)
        cmd = [sys.executable, runner, instp, "--solver", "our", "--timelimit", str(tl)]
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, env=e)
        outer = time.time() - t0
        line = ""
        for ln in reversed(p.stdout.strip().splitlines()):
            if ln.strip().startswith("{"):
                line = ln.strip(); break
        try: r = json.loads(line)
        except Exception: r = {"parse_error": line[:160], "stderr": p.stderr[-300:]}
        r["cfg"] = cfg; r["tl"] = tl; r["wall_outer"] = round(outer, 1)
        rows.append(r)
        print(f"{inst:9}{cfg:8}{str(r.get('feasible')):6}{str(r.get('objective')):>14}"
              f"{str(r.get('obj1')):>9}{str(r.get('obj2')):>8}{str(r.get('obj3')):>8}"
              f"{str(r.get('elapsed')):>9}{str(r.get('n_violations')):>6}")
        sys.stdout.flush()

print("\n=== Z1 vs base (same timelimit) ===")
by = {}
for r in rows:
    by.setdefault(r.get("instance"), {})[r["cfg"]] = r
for inst, d in by.items():
    b = d.get("base", {})
    line = f"  {inst:9} base.Z1={b.get('obj1')}"
    for cfg in ("cap48", "cap64"):
        c = d.get(cfg, {})
        if c.get("obj1") is not None and b.get("obj1") is not None:
            dz = c["obj1"] - b["obj1"]
            line += f"  {cfg}.Z1={c.get('obj1')}(d{dz:+.0f},feas={c.get('feasible')})"
    print(line)

(ROOT / "results").mkdir(exist_ok=True)
(ROOT / "results" / "z1_candcap_speed.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nWROTE results/z1_candcap_speed.json")
