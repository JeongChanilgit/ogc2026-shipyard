"""T1 burst 3: full-20 @1000 ON/OFF x2 paired -- the long-tl leg of the
"hypothesis validation = ALL instances" rule (user directive 2026-06-11).
~8h unattended (20 inst x ~750s avg x 4 sweeps / conc 2).

Summary -> results/_t1_batch3_summary.txt
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
ALL20 = [f"prob_{i}" for i in range(1, 21)]


def run(cmd, timeout):
    t0 = time.monotonic()
    print(f"\n[batch3] >>> {' '.join(cmd[1:])}", flush=True)
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        out = p.stdout
    except subprocess.TimeoutExpired:
        out = "(TIMEOUT)"
    print(out, flush=True)
    print(f"[batch3] <<< done in {time.monotonic() - t0:.0f}s", flush=True)


def met_of(tag, inst):
    p = ROOT / "results" / "capture" / tag / f"{inst}.json"
    if not p.exists():
        return None
    try:
        return json.load(open(p, encoding="utf-8")).get("met")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    a = ap.parse_args()
    for rep in range(1, a.reps + 1):
        run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
             "--instances", "ALL", "--timelimit", "1000",
             "--concurrency", "2", "--tag", f"sweep1k_on_r{rep}",
             "--env", "OGC_LONGTL_RACE=1"], timeout=14000)
        run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
             "--instances", "ALL", "--timelimit", "1000",
             "--concurrency", "2", "--tag", f"sweep1k_off_r{rep}"],
            timeout=14000)

    lines = ["\n=== burst3: full-20 @1000 ON(x%d) vs OFF(x%d), per-inst min ==="
             % (a.reps, a.reps)]
    worst = []
    for inst in ALL20:
        on = [m for m in (met_of(f"sweep1k_on_r{r}", inst)
                          for r in range(1, a.reps + 1)) if m]
        off = [m for m in (met_of(f"sweep1k_off_r{r}", inst)
                           for r in range(1, a.reps + 1)) if m]
        if not on or not off:
            lines.append(f"  {inst:9} MISSING on={len(on)} off={len(off)}")
            continue
        feas_bad = [m for m in on if not m.get("feas")]
        mo = min(m["obj"] for m in on)
        mf = min(m["obj"] for m in off)
        d = 100 * (mo - mf) / mf if mf else 0.0
        worst.append((d, inst))
        zon = max(m["z1"] for m in on)
        zoff = max(m["z1"] for m in off)
        lines.append(f"  {inst:9} ON {mo:>9.0f} (z1<={zon:.0f})  "
                     f"OFF {mf:>9.0f} (z1<={zoff:.0f})  {d:+6.1f}%"
                     + ("  !!INFEAS" if feas_bad else ""))
    worst.sort(reverse=True)
    lines.append(f"  worst deltas: {[(i, round(d, 1)) for d, i in worst[:4]]}")
    text = "\n".join(lines)
    print(text, flush=True)
    (ROOT / "results" / "_t1_batch3_summary.txt").write_text(
        text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
