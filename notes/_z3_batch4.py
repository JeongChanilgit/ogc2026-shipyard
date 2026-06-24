"""z3 batch 4 (2026-06-11, goal: beat competitor table on >=15/20 @600s):

  a. kill-test prob_4, prob_18   -- time-aware CP-SAT reassign + full decode
                                    (informational gate for the temporal track)
  b. FB-uncap mini A/B           -- prob_4/13/18 @600, fb vs base x1 (fail-fast)
  c. base600_r1, base600_r2      -- full-20 @600 baseline (race ON), ALWAYS
                                    -> the goal's win-count denominator
  c2. off600_r1                  -- full-20 @600 race OFF x1 -> T1 adoption
                                    evidence at the goal tl (batch2 died mid-
                                    sweep; @300 evidence abandoned for @600)
  d. fb600_r1, fb600_r2          -- full-20 @600 FB-uncap arm, only if (b) gate

Summary -> results/_z3_batch4_summary.txt (win counts vs competitor table).
Run AFTER batch2 finishes (machine must be free).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
ALL20 = [f"prob_{i}" for i in range(1, 21)]
MINI = ["prob_4", "prob_13", "prob_18"]

BASE_ENV = "OGC_LONGTL_RACE=1"
FB_ENV = ("OGC_LONGTL_RACE=1,OGC_FRONTB_MULTI=4,OGC_FRONTB_REDECODE=1,"
          "OGC_FRONTB_REDECODE_K=6,OGC_FRONTB_TRIES=48,"
          "OGC_FRONTB_SWAP_TOP=80,OGC_FRONTB_STALL=3")

COMP = {k: v["obj"] for k, v in json.load(
    open(ROOT / "notes" / "competitor-2026-06-11.json", encoding="utf-8")
)["competitor"].items()}


def run(cmd, timeout):
    t0 = time.monotonic()
    print(f"\n[batch4] >>> {' '.join(cmd[1:])}", flush=True)
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        out = "(TIMEOUT)"
    print(out[-4000:], flush=True)
    print(f"[batch4] <<< done in {time.monotonic() - t0:.0f}s", flush=True)
    return out


def cap(insts, tag, env, conc, tl=600, timeout=8000):
    run([PYEXE, str(ROOT / "notes" / "_capture20.py"),
         "--instances", ",".join(insts) if insts != ALL20 else "ALL",
         "--timelimit", str(tl), "--concurrency", str(conc),
         "--tag", tag, "--env", env], timeout)


def met_of(tag, inst):
    p = ROOT / "results" / "capture" / tag / f"{inst}.json"
    if not p.exists():
        return None
    try:
        return json.load(open(p, encoding="utf-8")).get("met")
    except Exception:
        return None


def main():
    lines = ["=== z3 batch4 summary ==="]

    # a. kill-tests (informational; ~25 min each, workers=2)
    for inst in ("prob_4", "prob_18"):
        out = run([PYEXE, str(ROOT / "notes" / "_z3_killtest.py"),
                   "--inst", inst, "--alpha", "0.7", "--cpsat-s", "120",
                   "--decode-s", "300", "--rounds", "3"], timeout=2400)
        tail = [ln for ln in out.splitlines() if ln.strip()][-3:]
        lines.append(f"  killtest {inst}: " + " | ".join(tail))

    # b. FB mini A/B @600 (fail-fast)
    cap(MINI, "fbmini_on", FB_ENV, conc=3)
    cap(MINI, "fbmini_off", BASE_ENV, conc=3)
    z3_on = z3_off = 0.0
    worst_reg = 0.0
    ok = True
    for i in MINI:
        mo, mf = met_of("fbmini_on", i), met_of("fbmini_off", i)
        if not mo or not mf or not mo.get("feas"):
            ok = False
            lines.append(f"  fbmini {i}: MISSING/infeas on={mo} off={mf}")
            continue
        z3_on += mo["z3"]; z3_off += mf["z3"]
        reg = 100 * (mo["obj"] - mf["obj"]) / mf["obj"]
        worst_reg = max(worst_reg, reg)
        lines.append(f"  fbmini {i}: ON obj={mo['obj']:.0f} z3={mo['z3']:.0f}"
                     f"  OFF obj={mf['obj']:.0f} z3={mf['z3']:.0f}  {reg:+.1f}%")
    gate = ok and (z3_on <= 0.9 * z3_off) and (worst_reg <= 5.0)
    lines.append(f"  fbmini gate: {'PASS' if gate else 'FAIL'} "
                 f"(z3 {z3_on:.0f} vs {z3_off:.0f}, worst obj reg "
                 f"{worst_reg:+.1f}%)")

    # c. baseline @600 x2 (always -- goal denominator); conc 3 = eval-faithful
    for r in (1, 2):
        cap(ALL20, f"base600_r{r}", BASE_ENV, conc=3, timeout=9000)

    # c2. race OFF @600 x1 -- T1 ON-vs-OFF evidence at the goal tl
    cap(ALL20, "off600_r1", "", conc=3, timeout=9000)

    # d. FB arm @600 x2 (gated)
    if gate:
        for r in (1, 2):
            cap(ALL20, f"fb600_r{r}", FB_ENV, conc=3, timeout=9000)

    # ---- win-count summary ----------------------------------------------
    def wins(tags):
        w, rows = 0, []
        for inst in ALL20:
            ms = [m for m in (met_of(t, inst) for t in tags)
                  if m and m.get("feas")]
            if not ms:
                rows.append(f"    {inst:9} MISSING")
                continue
            o = min(m["obj"] for m in ms)
            z3 = min(m["z3"] for m in ms)
            t = COMP[inst]
            win = o < t
            w += win
            rows.append(f"    {inst:9} {o:>9.0f} vs {t:>9.0f} (z3 {z3:>5.0f})"
                        f"  {'WIN' if win else 'lose'}")
        return w, rows

    wb, rb = wins(["base600_r1", "base600_r2"])
    lines.append(f"\n  base600 (min of x2) wins: {wb}/20 (need >=15)")
    lines += rb

    # T1 race ON vs OFF @600 (min of ON x2 vs OFF x1, per instance)
    lines.append("\n  T1 @600: race ON(min x2) vs OFF(x1):")
    for inst in ALL20:
        on = [m for m in (met_of(f"base600_r{r}", inst) for r in (1, 2)) if m]
        off = met_of("off600_r1", inst)
        if not on or not off:
            lines.append(f"    {inst:9} MISSING")
            continue
        mo = min(m["obj"] for m in on)
        d = 100 * (mo - off["obj"]) / off["obj"] if off["obj"] else 0.0
        lines.append(f"    {inst:9} ON {mo:>9.0f}  OFF {off['obj']:>9.0f}"
                     f"  {d:+6.1f}%")
    if gate:
        wf, rf = wins(["fb600_r1", "fb600_r2"])
        lines.append(f"\n  fb600 (min of x2) wins: {wf}/20")
        lines += rf
        wc, _ = wins(["base600_r1", "base600_r2", "fb600_r1", "fb600_r2"])
        lines.append(f"\n  combined best-of wins: {wc}/20")

    text = "\n".join(lines)
    print(text, flush=True)
    (ROOT / "results" / "_z3_batch4_summary.txt").write_text(
        text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
