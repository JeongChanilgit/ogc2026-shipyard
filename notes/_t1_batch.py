"""T1/T2 unattended measurement batch (2026-06-11).  Runs the full remaining
validation program SEQUENTIALLY (machine-exclusive timing runs first, then the
conc=2 A/B captures), so one launch carries ~2h of measurements.

Stages:
  1. prob_6  race leg @300  -- v2.1 REFUND path validation (expect race_refund)
  2. prob_20 race leg @300  -- race-win path validation (expect ~590K vs 693K)
  3. T2 OGC_DEV_DET check   -- prob_6/12/19 x 2 runs @100 (reproducibility)
  4. A/B mini-gate @300     -- {13,6,20,11} x N=3, race ON vs OFF, conc=2
  5. prob_13 @1000 x1 each  -- ON vs OFF (indicative, N=1)

Writes a final compact summary to results/_t1_batch_summary.txt and stdout.
Usage: python notes/_t1_batch.py [--skip-ab] [--skip-1000]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
AB_INSTS = "prob_13,prob_6,prob_20,prob_11"


def run(cmd, timeout):
    t0 = time.monotonic()
    print(f"\n[batch] >>> {' '.join(cmd[1:])}", flush=True)
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        out = p.stdout
    except subprocess.TimeoutExpired:
        out = "(TIMEOUT)"
    print(out, flush=True)
    print(f"[batch] <<< done in {time.monotonic() - t0:.0f}s", flush=True)
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
    ap.add_argument("--skip-ab", action="store_true")
    ap.add_argument("--skip-1000", action="store_true")
    a = ap.parse_args()
    lines = []

    # 1+2: probe race legs (sequential, exclusive)
    for inst in ("prob_6", "prob_20"):
        run([PYEXE, str(ROOT / "notes" / "_t1_probe13.py"),
             "--timelimit", "300", "--skip-default", "--skip-raster",
             "--race", "--inst", inst], timeout=700)

    # 3: T2 determinization check
    run([PYEXE, str(ROOT / "notes" / "_t2_devdet_check.py")], timeout=1500)

    # 4: A/B mini-gate, N=3 paired, conc=2
    if not a.skip_ab:
        for rep in (1, 2, 3):
            run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
                 "--instances", AB_INSTS, "--timelimit", "300",
                 "--concurrency", "2", "--tag", f"race_on_r{rep}",
                 "--env", "OGC_LONGTL_RACE=1"], timeout=2400)
            run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
                 "--instances", AB_INSTS, "--timelimit", "300",
                 "--concurrency", "2", "--tag", f"race_off_r{rep}"],
                timeout=2400)

    # 5: prob_13 @1000, one each (indicative)
    if not a.skip_1000:
        run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
             "--instances", "prob_13", "--timelimit", "1000",
             "--concurrency", "1", "--tag", "race_on_1000",
             "--env", "OGC_LONGTL_RACE=1"], timeout=1500)
        run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
             "--instances", "prob_13", "--timelimit", "1000",
             "--concurrency", "1", "--tag", "race_off_1000"], timeout=1500)

    # ---- summary table ------------------------------------------------------
    lines.append("\n=== T1 A/B summary (race ON vs OFF, tl=300, N=3) ===")
    if not a.skip_ab:
        for inst in AB_INSTS.split(","):
            on = [met_of(f"race_on_r{r}", inst) for r in (1, 2, 3)]
            off = [met_of(f"race_off_r{r}", inst) for r in (1, 2, 3)]
            on = [m for m in on if m]
            off = [m for m in off if m]
            fmt = lambda ms, k: [round(m[k]) for m in ms] if ms else "-"
            lines.append(
                f"  {inst:9} ON  obj={fmt(on, 'obj')} z1={fmt(on, 'z1')}\n"
                f"  {'':9} OFF obj={fmt(off, 'obj')} z1={fmt(off, 'z1')}")
            if on and off:
                mo, mf = min(m["obj"] for m in on), min(m["obj"] for m in off)
                ao = sum(m["obj"] for m in on) / len(on)
                af = sum(m["obj"] for m in off) / len(off)
                lines.append(f"  {'':9} min {mo:.0f} vs {mf:.0f} "
                             f"({100 * (mo - mf) / mf:+.1f}%)   "
                             f"mean {ao:.0f} vs {af:.0f} "
                             f"({100 * (ao - af) / af:+.1f}%)")
    if not a.skip_1000:
        on = met_of("race_on_1000", "prob_13")
        off = met_of("race_off_1000", "prob_13")
        lines.append(f"  prob_13@1000 ON  {on}")
        lines.append(f"  prob_13@1000 OFF {off}")
    text = "\n".join(lines)
    print(text, flush=True)
    (ROOT / "results" / "_t1_batch_summary.txt").write_text(
        text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
