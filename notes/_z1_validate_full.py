# -*- coding: utf-8 -*-
"""Final validation: FAST_POSITIONS TOP=4 (full) vs base across a train subset @60s.
Small instances (1/5/8) = regression guard; large (6/11/14/19/20) = expected win."""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(r"C:\claude-develop\OGC2026")
runner = str(ROOT / "tools" / "run_solver_once.py")
CONFIGS = {"base": {}, "full": {"OGC_FAST_POSITIONS": "1", "OGC_FAST_POS_TOP": "4"}}
INSTS = ["prob_1", "prob_5", "prob_8", "prob_6", "prob_11", "prob_14", "prob_19", "prob_20"]
TL = 60
rows = []
print(f"{'inst':9}{'cfg':6}{'feas':6}{'Z1':>10}{'objective':>16}{'elapsed':>9}{'viol':>5}")
for inst in INSTS:
    instp = str(ROOT / "instances" / "train" / f"{inst}.json")
    for cfg, envadd in CONFIGS.items():
        e = dict(os.environ); e.update(envadd)
        p = subprocess.run([sys.executable, runner, instp, "--solver", "our",
                            "--timelimit", str(TL)], capture_output=True, text=True, env=e)
        line = ""
        for ln in reversed(p.stdout.strip().splitlines()):
            if ln.strip().startswith("{"): line = ln.strip(); break
        try: r = json.loads(line)
        except Exception: r = {"err": line[:120]}
        r.update({"inst": inst, "cfg": cfg})
        rows.append(r)
        print(f"{inst:9}{cfg:6}{str(r.get('feasible')):6}{str(r.get('obj1')):>10}"
              f"{str(r.get('objective')):>16}{str(r.get('elapsed')):>9}{str(r.get('n_violations')):>5}")
        sys.stdout.flush()

print("\n=== full vs base @60s (Z1; negative delta = full better) ===")
by = {(r["inst"], r["cfg"]): r for r in rows}
wins = losses = ties = 0
for inst in INSTS:
    b = by.get((inst, "base"), {}).get("obj1")
    f = by.get((inst, "full"), {}).get("obj1")
    bf = by.get((inst, "full"), {}).get("feasible")
    if b is None or f is None:
        print(f"  {inst:9} base={b} full={f} (parse issue)"); continue
    d = f - b
    tag = "WIN" if d < -0.5 else ("LOSS" if d > 0.5 else "tie")
    if tag == "WIN": wins += 1
    elif tag == "LOSS": losses += 1
    else: ties += 1
    print(f"  {inst:9} base.Z1={b:>8.0f}  full.Z1={f:>8.0f}  d={d:>+9.0f}  {tag}  feas={bf}")
print(f"\n  TALLY: full WINS={wins}  LOSSES={losses}  TIES={ties}")
(ROOT / "results" / "z1_validate_full_60s.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("WROTE results/z1_validate_full_60s.json")
