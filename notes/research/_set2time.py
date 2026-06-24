"""set2 −1 diagnosis: run LEGACY on set2 timeout instances at TL=120, measure true
wall vs TL, and surface stage timing (stderr) to find which step escapes hard_stop.

  python notes/research/_set2time.py prob_25 prob_26
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
import ogc_analysis as OA                      # noqa: E402
sys.path.insert(0, str(ROOT / "src"))
import myalgorithm as M                        # noqa: E402

os.environ["OGC_HYBRID"] = "0"                 # pure legacy
os.environ["OGC_LEVER_DEBUG"] = "1"            # prints decode_deadline / hard_stop


def main():
    TL = float(os.environ.get("FS_TL", "120"))
    targets = sys.argv[1:] or ["prob_25", "prob_26"]
    for name in targets:
        prob = json.load(open(ROOT / "instances" / "train" / f"{name}.json", encoding="utf-8"))
        nblk = len(prob["blocks"]); nbay = len(prob["bays"])
        t0 = time.monotonic()
        sol = M._legacy_algorithm(prob, TL)
        dt = time.monotonic() - t0
        feas, o, z1, z2, z3 = OA.obj_tuple(prob, sol)
        over = dt - TL
        print(f"{name}: blocks={nblk} bays={nbay} | obj={o:.0f} z1={z1:.0f} feas={feas} "
              f"| wall={dt:.1f}s TL={TL:.0f} OVER={over:+.1f}s "
              f"{'*** -1 ON SERVER ***' if over > 3 else 'ok'}", flush=True)


if __name__ == "__main__":
    main()
