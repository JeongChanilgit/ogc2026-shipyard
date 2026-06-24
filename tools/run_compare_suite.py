"""Run BOTH solvers (official baseline + ours) over a set of instances and
collect a comparison summary.

Each (instance, solver) runs as an isolated subprocess (tools/run_solver_once.py)
with a hard wall-clock timeout, so a hang/overrun on one job can never stall the
whole suite -- it is recorded as a failure (== the eval server's -1).

Run this UNDER the solver python (so sys.executable is the right interpreter):
    <ogc2025-python> tools/run_compare_suite.py --timelimit 60 \
        --outdir results/update_compare_<ts> --our-jobs 4 --baseline-jobs 6

Writes per-job score JSON + solution JSON into outdir, and a combined
summary.json.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "tools" / "run_solver_once.py"
PY = sys.executable  # run children with the same interpreter as this orchestrator


def _parse_last_json(text: str):
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


def run_one(inst: Path, solver: str, timelimit: float, outdir: Path,
            hard_timeout: float) -> dict:
    score_out = outdir / f"score_{inst.stem}__{solver}.json"
    sol_out = outdir / f"sol_{inst.stem}__{solver}.json"
    cmd = [PY, str(RUNNER), str(inst), "--solver", solver,
           "--timelimit", str(timelimit),
           "--out", str(score_out), "--save-sol", str(sol_out)]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=hard_timeout)
        wall = time.monotonic() - t0
        res = None
        if score_out.exists():
            try:
                res = json.loads(score_out.read_text(encoding="utf-8"))
            except Exception:
                res = None
        if res is None:
            res = _parse_last_json(p.stdout)
        if res is None:
            res = {"instance": inst.stem, "solver": solver, "ok": False,
                   "feasible": False,
                   "error": f"no-json (rc={p.returncode}) {p.stderr[-300:]}"}
        res["wall"] = round(wall, 2)
        res["returncode"] = p.returncode
        res["deadline_fail"] = bool(wall > timelimit)
        res["judge_ok"] = bool(res.get("feasible")) and not res["deadline_fail"]
    except subprocess.TimeoutExpired:
        wall = time.monotonic() - t0
        res = {"instance": inst.stem, "solver": solver, "ok": False,
               "feasible": False, "error": "HARD_TIMEOUT",
               "wall": round(wall, 2),
               "n_bays": None, "n_blocks": None,
               "deadline_fail": True, "judge_ok": False}
    status = "OK " if res.get("judge_ok", res.get("feasible")) else "FAIL"
    print(f"  [{status}] {inst.stem:10} {solver:8} "
          f"obj={res.get('objective')} wall={res.get('wall')}s", flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="instances/train/prob_*.json")
    ap.add_argument("--timelimit", type=float, default=60.0)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--our-jobs", type=int, default=4)
    ap.add_argument("--baseline-jobs", type=int, default=6)
    ap.add_argument("--our-hardcap", type=float, default=None,
                    help="hard wall-clock kill (s) for our jobs")
    ap.add_argument("--baseline-hardcap", type=float, default=None,
                    help="hard wall-clock kill (s) for baseline jobs")
    ap.add_argument("--solvers", default="baseline,our")
    args = ap.parse_args()

    outdir = ROOT / args.outdir if not Path(args.outdir).is_absolute() else Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    instances = sorted(ROOT.glob(args.glob),
                       key=lambda p: int("".join(c for c in p.stem if c.isdigit()) or 0))
    if not instances:
        print(f"[suite] no instances match {args.glob}")
        return 2
    solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    print(f"[suite] {len(instances)} instances x {solvers}  timelimit={args.timelimit}s")
    print(f"[suite] outdir={outdir}")

    all_results: list[dict] = []
    for solver in solvers:
        jobs = args.our_jobs if solver == "our" else args.baseline_jobs
        # our solver uses up to 4 cores/process; baseline is ~single-threaded.
        if solver == "our":
            hard_timeout = (args.our_hardcap if args.our_hardcap
                            else args.timelimit * 3.0 + 60)
        else:
            hard_timeout = (args.baseline_hardcap if args.baseline_hardcap
                            else args.timelimit * 2.5 + 60)
        print(f"\n[suite] === {solver} wave (concurrency={jobs}, "
              f"hard_timeout={hard_timeout:.0f}s) ===", flush=True)
        t0 = time.monotonic()
        with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(run_one, inst, solver, args.timelimit, outdir,
                              hard_timeout): inst for inst in instances}
            for fut in cf.as_completed(futs):
                all_results.append(fut.result())
        print(f"[suite] {solver} wave done in {time.monotonic()-t0:.0f}s", flush=True)

    summary = {
        "timelimit": args.timelimit,
        "solvers": solvers,
        "n_instances": len(instances),
        "results": all_results,
    }
    (outdir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n[suite] summary -> {outdir/'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
