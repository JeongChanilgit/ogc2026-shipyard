"""Best-recipe probe sweep: ban-feedback + 3 orders + repack + retime @ a=0.7.
Maps the expected per-instance gain of the future in-pipeline z3-race stage.
Light load (workers=2)."""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"

INSTS = ["prob_11", "prob_18", "prob_3", "prob_17", "prob_14", "prob_13",
         "prob_5", "prob_12"]

for inst in INSTS:
    t0 = time.monotonic()
    print(f"\n[v4sweep] >>> {inst}", flush=True)
    p = subprocess.run(
        [PYEXE, str(ROOT / "notes" / "_z3_killtest2.py"), "--inst", inst,
         "--alpha", "0.7", "--rounds", "8", "--cpsat-s", "90",
         "--decode-s", "180", "--retime-s", "60", "--orders", "3",
         "--ban", "--repack"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=3000)
    print((p.stdout or "") + (p.stderr or ""), flush=True)
    print(f"[v4sweep] <<< {inst} in {time.monotonic() - t0:.0f}s", flush=True)
print("[v4sweep] all done", flush=True)
sys.exit(0)
