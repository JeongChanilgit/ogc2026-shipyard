"""z3 batch 5 (fire AFTER batch4 AND after z3race is wired into myalgorithm):

  a. fb600_r1, fb600_r2          -- FB-uncap full-20 @600 x2 (batch4's gate
                                    misjudged the mini: obj gains -18.6%/-3.8%
                                    were real, z3-sum criterion missed z2)
  b. z3race mini                 -- prob_16/12/19/6 @600, OGC_Z3_RACE=1 vs base
                                    (fail-fast; base600_r{1,2} are the OFF arm)
  c. z3race full-20 @600 x2      -- only if (b): ON min < OFF min on >=2 of 4
                                    AND no mini instance regresses >5%

Summary -> results/_z3_batch5_summary.txt  (win counts vs competitor)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
ALL20 = [f"prob_{i}" for i in range(1, 21)]
MINI = ["prob_16", "prob_12", "prob_19", "prob_6"]

FB_ENV = ("OGC_LONGTL_RACE=1,OGC_FRONTB_MULTI=4,OGC_FRONTB_REDECODE=1,"
          "OGC_FRONTB_REDECODE_K=6,OGC_FRONTB_TRIES=48,"
          "OGC_FRONTB_SWAP_TOP=80,OGC_FRONTB_STALL=3")
Z3_ENV = "OGC_LONGTL_RACE=1,OGC_Z3_RACE=1,OGC_Z3RACE_S=240"
T5_ENV = "OGC_LONGTL_RACE=1,OGC_T5_CANDS=1"
COMBO_ENV = FB_ENV + ",OGC_T5_CANDS=1"   # +Z3 appended at runtime if gate

COMP = {k: v["obj"] for k, v in json.load(
    open(ROOT / "notes" / "competitor-2026-06-11.json", encoding="utf-8")
)["competitor"].items()}


def run(cmd, timeout):
    t0 = time.monotonic()
    print(f"\n[batch5] >>> {' '.join(cmd[1:])}", flush=True)
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        out = "(TIMEOUT)"
    print(out[-3000:], flush=True)
    print(f"[batch5] <<< done in {time.monotonic() - t0:.0f}s", flush=True)


def cap(insts, tag, env, conc, timeout=9000):
    args = [PYEXE, str(ROOT / "notes" / "_capture20.py"),
            "--instances", ",".join(insts) if insts != ALL20 else "ALL",
            "--timelimit", "600", "--concurrency", str(conc), "--tag", tag]
    if env:
        args += ["--env", env]
    run(args, timeout)


def met_of(tag, inst):
    p = ROOT / "results" / "capture" / tag / f"{inst}.json"
    if not p.exists():
        return None
    try:
        return json.load(open(p, encoding="utf-8")).get("met")
    except Exception:
        return None


def wins(tags):
    w, rows = 0, []
    for inst in ALL20:
        ms = [m for m in (met_of(t, inst) for t in tags) if m and m.get("feas")]
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


def main():
    lines = ["=== z3 batch5 summary ==="]

    # a. FB-uncap full-20 @600 x2
    for r in (1, 2):
        cap(ALL20, f"fb600_r{r}", FB_ENV, conc=3)

    # a2. T5 skyline candidates full-20 @600 x2 (structural realizer lever)
    for r in (1, 2):
        cap(ALL20, f"t5600_r{r}", T5_ENV, conc=3)

    # b. z3race mini (OFF arm = existing base600_r1/r2)
    cap(MINI, "z3mini_on", Z3_ENV, conc=2)   # conc 2: z3race adds CP-SAT load
    better, worst_reg = 0, 0.0
    ok = True
    for i in MINI:
        mo = met_of("z3mini_on", i)
        offs = [m for m in (met_of(f"base600_r{r}", i) for r in (1, 2)) if m]
        if not mo or not mo.get("feas") or not offs:
            ok = False
            lines.append(f"  z3mini {i}: MISSING/infeas")
            continue
        mf = min(m["obj"] for m in offs)
        reg = 100 * (mo["obj"] - mf) / mf
        worst_reg = max(worst_reg, reg)
        better += mo["obj"] < mf
        lines.append(f"  z3mini {i}: ON {mo['obj']:.0f} (z3 {mo['z3']:.0f})"
                     f"  OFFmin {mf:.0f}  {reg:+.1f}%")
    gate = ok and better >= 2 and worst_reg <= 5.0
    lines.append(f"  z3mini gate: {'PASS' if gate else 'FAIL'} "
                 f"(better {better}/4, worst reg {worst_reg:+.1f}%)")

    # c. z3race full-20 x2 (gated)
    if gate:
        for r in (1, 2):
            cap(ALL20, f"z3race600_r{r}", Z3_ENV, conc=2, timeout=12000)

    # e. kitchen-sink combo x1 (interaction test)
    combo = COMBO_ENV + (",OGC_Z3_RACE=1,OGC_Z3RACE_S=240" if gate else "")
    cap(ALL20, "combo600_r1", combo, conc=2, timeout=12000)

    wb, rb = wins(["fb600_r1", "fb600_r2"])
    lines.append(f"\n  fb600 (min x2) wins: {wb}/20")
    lines += rb
    wt, rt = wins(["t5600_r1", "t5600_r2"])
    lines.append(f"\n  t5600 (min x2) wins: {wt}/20")
    lines += rt
    wk, rk = wins(["combo600_r1"])
    lines.append(f"\n  combo600 (x1) wins: {wk}/20")
    lines += rk
    if gate:
        wz, rz = wins(["z3race600_r1", "z3race600_r2"])
        lines.append(f"\n  z3race600 (min x2) wins: {wz}/20")
        lines += rz
    tags_all = (["base600_r1", "base600_r2", "fb600_r1", "fb600_r2",
                 "t5600_r1", "t5600_r2", "combo600_r1"]
                + (["z3race600_r1", "z3race600_r2"] if gate else []))
    wc, rc = wins(tags_all)
    lines.append(f"\n  combined best-of wins: {wc}/20 (need >=15)")
    lines += rc

    text = "\n".join(lines)
    print(text, flush=True)
    (ROOT / "results" / "_z3_batch5_summary.txt").write_text(
        text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
