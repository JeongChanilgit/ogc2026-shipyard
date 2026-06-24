"""Sequential v3 kill-test sweep over the big-loss instances (light load:
workers=2 + single decode), logging one summary line per instance.

Targets chosen from notes/_z3_targets.py: instances needing z3 cuts >= 40%
(excluding prob_4: parked, model bound 50 > needed 32; prob_20: pref-volume
infeasible bay1=1.15).
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

INSTS = ["prob_16", "prob_17", "prob_11", "prob_14", "prob_13", "prob_3"]

for inst in INSTS:
    t0 = time.monotonic()
    print(f"\n[v3sweep] >>> {inst}", flush=True)
    p = subprocess.run(
        [PYEXE, str(ROOT / "notes" / "_z3_killtest2.py"), "--inst", inst,
         "--alpha", "0.7", "--rounds", "4", "--cpsat-s", "120",
         "--decode-s", "180", "--retime-s", "90"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=2400)
    print((p.stdout or "") + (p.stderr or ""), flush=True)
    print(f"[v3sweep] <<< {inst} in {time.monotonic() - t0:.0f}s", flush=True)
print("[v3sweep] all done", flush=True)
sys.exit(0)
