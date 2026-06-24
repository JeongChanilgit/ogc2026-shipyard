"""FastFloor adoption A/B @300 (2026-06-12): ON(OGC_FASTFLOOR=1) vs OFF, full-20
x2 each, conc=3 (eval-faithful, batch4 convention).
Win = strict obj < competitor (notes/competitor-2026-06-11.json).
Summary -> results/_ff_ab_summary.txt
"""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYEXE = r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"
ALL20 = [f"prob_{i}" for i in range(1, 21)]
COMP = {k: v["obj"] for k, v in json.load(
    open(ROOT / "notes" / "competitor-2026-06-11.json", encoding="utf-8")
)["competitor"].items()}


def run(cmd, timeout):
    print(f"\n[ffab] >>> {' '.join(cmd[1:])}", flush=True)
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        out = "(TIMEOUT)"
    print(out[-2000:], flush=True)
    print(f"[ffab] <<< done in {time.monotonic() - t0:.0f}s", flush=True)


def cap(tag, env, tl=300, conc=3, timeout=9000):
    run([PYEXE, str(ROOT / "notes" / "_capture20.py"), "--instances", "ALL",
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
    for r in (1, 2):
        cap(f"ffon300_r{r}", "OGC_FASTFLOOR=1")
        cap(f"ffoff300_r{r}", "")

    lines = ["=== fastfloor A/B @300 full-20 x2 (conc=3) ==="]
    lines.append(f"{'inst':9} {'comp':>10} {'on_best':>10} {'off_best':>10} "
                 f"{'on-off%':>8}  on_z1 off_z1  verdict")
    won_on = won_off = on_better = 0
    inf = float("inf")
    for i in ALL20:
        on = [met_of(f"ffon300_r{r}", i) for r in (1, 2)]
        off = [met_of(f"ffoff300_r{r}", i) for r in (1, 2)]
        on_ok = [m for m in on if m and m.get("feas")]
        off_ok = [m for m in off if m and m.get("feas")]
        bon = min((m["obj"] for m in on_ok), default=inf)
        boff = min((m["obj"] for m in off_ok), default=inf)
        zon = min((m.get("z1", -1) for m in on_ok), default=-1)
        zoff = min((m.get("z1", -1) for m in off_ok), default=-1)
        if bon < COMP[i]:
            won_on += 1
        if boff < COMP[i]:
            won_off += 1
        if bon < boff:
            on_better += 1
        d = (f"{100 * (bon - boff) / boff:+7.1f}%"
             if boff not in (0, inf) and bon != inf else "      --")
        verdict = ("ON-win" if bon < COMP[i] <= boff else
                   "OFF-win" if boff < COMP[i] <= bon else
                   "both" if bon < COMP[i] else "")
        def fmt(v):
            return f"{v:10.0f}" if v != inf else f"{'INFEAS':>10}"
        lines.append(f"{i:9} {COMP[i]:10.0f} {fmt(bon)} {fmt(boff)} {d}"
                     f"  {zon:5.0f} {zoff:6.0f}  {verdict}")
    lines.append(f"\nwins vs competitor (best-of-2): ON {won_on}/20 | "
                 f"OFF {won_off}/20 | ON better than OFF: {on_better}/20")
    txt = "\n".join(lines)
    print(txt, flush=True)
    (ROOT / "results" / "_ff_ab_summary.txt").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
