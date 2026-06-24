# -*- coding: utf-8 -*-
"""A/B harness: base (all flags OFF) vs OGC_Z1_PUSH=1 on a few instances.
Verifies feasibility, objective-safety (push obj <= base obj), Z1 delta, wall<limit.
Run under ogc2025:  conda run -n ogc2025 python notes/_z1_ab.py"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
CONFIGS = {"base": {}, "push": {"OGC_Z1_PUSH": "1"}}
JOBS = [("prob_6", 60), ("prob_5", 60), ("prob_14", 120)]

rows = []
print(f"{'inst':9}{'cfg':6}{'feas':6}{'objective':>14}{'Z1':>9}{'Z2':>8}{'Z3':>8}{'elapsed':>9}{'viol':>6}")
for inst, tl in JOBS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    for cfg, envadd in CONFIGS.items():
        e = dict(os.environ)
        e.update(envadd)
        cmd = [sys.executable, runner, instp, "--solver", "our", "--timelimit", str(tl)]
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True, env=e)
        outer = time.time() - t0
        line = ""
        for ln in reversed(p.stdout.strip().splitlines()):
            if ln.strip().startswith("{"):
                line = ln.strip(); break
        try:
            r = json.loads(line)
        except Exception:
            r = {"parse_error": line[:200], "stderr": p.stderr[-400:]}
        r["cfg"] = cfg
        r["tl"] = tl
        r["wall_outer"] = round(outer, 1)
        rows.append(r)
        print(f"{inst:9}{cfg:6}{str(r.get('feasible')):6}{str(r.get('objective')):>14}"
              f"{str(r.get('obj1')):>9}{str(r.get('obj2')):>8}{str(r.get('obj3')):>8}"
              f"{str(r.get('elapsed')):>9}{str(r.get('n_violations')):>6}")
        sys.stdout.flush()

# verdict
print("\n=== VERDICT (objective-safety: push.feasible AND push.obj <= base.obj) ===")
byinst = {}
for r in rows:
    byinst.setdefault(r.get("instance"), {})[r["cfg"]] = r
for inst, d in byinst.items():
    b, p = d.get("base", {}), d.get("push", {})
    bo, po = b.get("objective"), p.get("objective")
    safe = bool(p.get("feasible")) and (po is not None and bo is not None and po <= bo + 1e-6)
    z1d = (None if (p.get("obj1") is None or b.get("obj1") is None)
           else round(p["obj1"] - b["obj1"], 2))
    walls_ok = all((d[c].get("elapsed") or 0) < d[c].get("tl", 1e9) for c in d)
    print(f"  {inst:9} safe={safe}  base.obj={bo} push.obj={po}  dZ1={z1d}  "
          f"feas(base,push)=({b.get('feasible')},{p.get('feasible')})  wall<limit={walls_ok}")

(ROOT / "results").mkdir(exist_ok=True)
(ROOT / "results" / "z1_push_ab.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\nWROTE results/z1_push_ab.json")
