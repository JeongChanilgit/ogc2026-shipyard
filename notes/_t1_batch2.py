"""T1 burst 2 (2026-06-11): the remaining no-regression evidence before
flipping OGC_LONGTL_RACE default ON.

Stages (fail-fast order):
  a. prob_13 race probe @300 x1   -- hope-guard sanity (race must STILL fire:
                                     raw 320K <= 2.0 x floor ~281K)
  b. full-20 @100, race ON, x1    -- smoke: T<RACE_MIN_T => byte-identical path
                                     + the -1 guard (conc 3, eval-faithful)
  c. prob_20 @1000 ON vs OFF x1   -- hope-guard validation (arms, z1>=3, raster
                                     raw ~3M hopeless -> warm refund; watch for
                                     regression vs OFF)
  d. full-20 @300 ON x2 + OFF x2  -- paired no-regression sweep (conc 2); also
                                     exercises the T5-OFF patched hot paths.

Summary -> results/_t1_batch2_summary.txt
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
ALL20 = ",".join(f"prob_{i}" for i in range(1, 21))


def run(cmd, timeout):
    t0 = time.monotonic()
    print(f"\n[batch2] >>> {' '.join(cmd[1:])}", flush=True)
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        out = p.stdout
    except subprocess.TimeoutExpired:
        out = "(TIMEOUT)"
    print(out, flush=True)
    print(f"[batch2] <<< done in {time.monotonic() - t0:.0f}s", flush=True)
    return out


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
    ap.add_argument("--skip-sweep", action="store_true",
                    help="skip stage d (the 2x2 full-20 sweep)")
    a = ap.parse_args()

    # a. hope-guard sanity on the winning instance
    run([PYEXE, str(ROOT / "notes" / "_t1_probe13.py"),
         "--timelimit", "300", "--skip-default", "--skip-raster",
         "--race"], timeout=700)

    # b. tl=100 smoke, race ON (cannot arm below RACE_MIN_T) + -1 guard
    run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
         "--instances", "ALL", "--timelimit", "100", "--concurrency", "3",
         "--tag", "race_on_100smoke", "--env", "OGC_LONGTL_RACE=1"],
        timeout=2400)

    # c. prob_20 @1000: hope guard (ON) vs OFF
    run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
         "--instances", "prob_20", "--timelimit", "1000",
         "--concurrency", "1", "--tag", "p20_on_1000",
         "--env", "OGC_LONGTL_RACE=1"], timeout=1500)
    run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
         "--instances", "prob_20", "--timelimit", "1000",
         "--concurrency", "1", "--tag", "p20_off_1000"], timeout=1500)

    # d. full-20 @300 paired sweep
    if not a.skip_sweep:
        for rep in (1, 2):
            run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
                 "--instances", "ALL", "--timelimit", "300",
                 "--concurrency", "2", "--tag", f"sweep_on_r{rep}",
                 "--env", "OGC_LONGTL_RACE=1"], timeout=4200)
            run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
                 "--instances", "ALL", "--timelimit", "300",
                 "--concurrency", "2", "--tag", f"sweep_off_r{rep}"],
                timeout=4200)

    # ---- summary -------------------------------------------------------------
    lines = ["\n=== burst2 summary ==="]
    on100 = [met_of("race_on_100smoke", i) for i in ALL20.split(",")]
    bad = [i for i, m in zip(ALL20.split(","), on100)
           if not m or not m.get("feas")]
    lines.append(f"  @100 smoke: feasible {20 - len(bad)}/20"
                 + (f"  FAIL: {bad}" if bad else "  (all ok)"))
    p20on, p20off = met_of("p20_on_1000", "prob_20"), met_of("p20_off_1000",
                                                             "prob_20")
    lines.append(f"  prob_20@1000 ON  {p20on}")
    lines.append(f"  prob_20@1000 OFF {p20off}")
    if not a.skip_sweep:
        lines.append("\n  full-20 @300 ON(x2) vs OFF(x2), per-instance min:")
        worst = []
        for inst in ALL20.split(","):
            on = [m for m in (met_of(f"sweep_on_r{r}", inst)
                              for r in (1, 2)) if m]
            off = [m for m in (met_of(f"sweep_off_r{r}", inst)
                               for r in (1, 2)) if m]
            if not on or not off:
                lines.append(f"    {inst:9} MISSING on={len(on)} off={len(off)}")
                continue
            mo = min(m["obj"] for m in on)
            mf = min(m["obj"] for m in off)
            d = 100 * (mo - mf) / mf if mf else 0.0
            worst.append((d, inst))
            zon = max(m["z1"] for m in on)
            zoff = max(m["z1"] for m in off)
            lines.append(f"    {inst:9} ON {mo:>9.0f} (z1<={zon:.0f})  "
                         f"OFF {mf:>9.0f} (z1<={zoff:.0f})  {d:+6.1f}%")
        worst.sort(reverse=True)
        lines.append(f"  worst deltas: {[(i, round(d, 1)) for d, i in worst[:4]]}")
    text = "\n".join(lines)
    print(text, flush=True)
    (ROOT / "results" / "_t1_batch2_summary.txt").write_text(
        text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
