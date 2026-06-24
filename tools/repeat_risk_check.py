"""Repeated safety check for OGC risk instances.

Runs one solver in fresh Python processes and records the evidence required by
notes/safe-foundation-goal.md: fail count, max wall time, max objective, and
objective explosion flags.  The default instance set is train prob_13..prob_20.

Examples:
    python tools/repeat_risk_check.py --runs 5 --timelimit 60
    python tools/repeat_risk_check.py instances/stress --runs 3 --timelimit 60
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RISK_INSTANCES = [
    ROOT / "instances" / "train" / f"prob_{idx}.json"
    for idx in range(13, 21)
]


def _resolve_instances(paths: list[str]) -> list[Path]:
    if not paths:
        return [p for p in DEFAULT_RISK_INSTANCES if p.exists()]
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(p.rglob("*.json")))
        elif p.exists():
            out.append(p)
        else:
            raise FileNotFoundError(p)
    seen = set()
    uniq = []
    for p in out:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def _json_from_stdout(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {
        "ok": False,
        "feasible": False,
        "error": "missing JSON result line",
        "stdout_tail": stdout[-1000:],
    }


def _run_once(instance: Path, solver: str, timelimit: float, timeout: float,
              run_id: str, out_dir: Path) -> dict:
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "run_solver_once.py"),
        str(instance),
        "--solver",
        solver,
        "--timelimit",
        str(timelimit),
    ]
    stdout_path = out_dir / f"{run_id}.stdout.txt"
    stderr_path = out_dir / f"{run_id}.stderr.txt"
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        elapsed_parent = time.perf_counter() - t0
        stdout_path.write_text(proc.stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(proc.stderr, encoding="utf-8", errors="replace")
        row = _json_from_stdout(proc.stdout)
        row.setdefault("ok", proc.returncode == 0)
        row["returncode"] = proc.returncode
        row["parent_elapsed"] = round(elapsed_parent, 3)
    except subprocess.TimeoutExpired as exc:
        elapsed_parent = time.perf_counter() - t0
        stdout_path.write_text(exc.stdout or "", encoding="utf-8", errors="replace")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8", errors="replace")
        row = {
            "ok": False,
            "feasible": False,
            "error": f"subprocess timeout after {timeout:.1f}s",
            "parent_elapsed": round(elapsed_parent, 3),
        }
    row.update({
        "run_id": run_id,
        "instance_path": str(instance),
        "instance": instance.stem,
        "solver": solver,
        "timelimit": timelimit,
    })
    return row


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _summarize(rows: list[dict], wall_margin: float) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("instance")), []).append(row)

    out = []
    for inst, inst_rows in sorted(grouped.items()):
        objectives = [
            float(r["objective"]) for r in inst_rows
            if r.get("feasible") and r.get("objective") is not None
        ]
        elapsed_vals = [
            float(r.get("elapsed", r.get("parent_elapsed", 0.0)))
            for r in inst_rows
            if r.get("elapsed") is not None or r.get("parent_elapsed") is not None
        ]
        med = _median(objectives)
        max_obj = max(objectives) if objectives else None
        explosion_threshold = None if med is None else med * 3.0
        explosion_count = 0
        if explosion_threshold is not None:
            explosion_count = sum(1 for obj in objectives if obj >= explosion_threshold)
        fail_count = sum(
            1 for r in inst_rows
            if not (r.get("ok") and r.get("feasible") and r.get("objective") is not None)
        )
        max_wall = max(elapsed_vals) if elapsed_vals else None
        timelimit = float(inst_rows[0].get("timelimit", 0.0) or 0.0)
        out.append({
            "instance": inst,
            "runs": len(inst_rows),
            "fail_count": fail_count,
            "min_objective": min(objectives) if objectives else None,
            "median_objective": med,
            "max_objective": max_obj,
            "explosion_threshold": explosion_threshold,
            "explosion_count": explosion_count,
            "max_wall": max_wall,
            "wall_margin_ok": (
                max_wall is not None and timelimit > 0
                and max_wall <= timelimit - wall_margin
            ),
        })
    return out


def _write_outputs(out_dir: Path, rows: list[dict], summary: list[dict],
                   args: argparse.Namespace) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rows.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "solver": args.solver,
            "runs": args.runs,
            "timelimit": args.timelimit,
            "wall_margin": args.wall_margin,
            "summary": summary,
        }, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    fieldnames = sorted({k for row in rows for k in row.keys()})
    with (out_dir / "rows.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Repeat Risk Check",
        "",
        f"- solver: {args.solver}",
        f"- runs: {args.runs}",
        f"- timelimit: {args.timelimit}",
        f"- wall_margin: {args.wall_margin}",
        "",
        "| instance | runs | fails | max wall | min obj | median obj | max obj | explosions | margin ok |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary:
        lines.append(
            "| {instance} | {runs} | {fail_count} | {max_wall} | "
            "{min_objective} | {median_objective} | {max_objective} | "
            "{explosion_count} | {wall_margin_ok} |".format(**item)
        )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run repeated solver safety checks.")
    ap.add_argument("instances", nargs="*", help="Instance files or directories")
    ap.add_argument("--solver", choices=["our", "baseline"], default="our")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--timelimit", type=float, default=60.0)
    ap.add_argument("--timeout", type=float, default=None,
                    help="Subprocess timeout per run; default=max(60, 1.25*T+30)")
    ap.add_argument("--wall-margin", type=float, default=3.0,
                    help="Target margin below timelimit for max wall")
    ap.add_argument("--strict-margin", action="store_true",
                    help="Return nonzero when max wall exceeds timelimit-margin")
    ap.add_argument("--out", default=None, help="Output directory")
    args = ap.parse_args()

    instances = _resolve_instances(args.instances)
    if not instances:
        print("[repeat] no instances found")
        return 2

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else ROOT / "results" / f"risk_repeat_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    timeout = args.timeout or max(60.0, 1.25 * args.timelimit + 30.0)

    rows: list[dict] = []
    for inst in instances:
        for run_idx in range(1, args.runs + 1):
            run_id = f"{inst.stem}_r{run_idx:02d}"
            print(f"[repeat] {run_id} solver={args.solver}")
            row = _run_once(inst, args.solver, args.timelimit, timeout, run_id, out_dir)
            rows.append(row)
            print(
                "[repeat]   feasible={feasible} obj={objective} elapsed={elapsed} "
                "error={error}".format(
                    feasible=row.get("feasible"),
                    objective=row.get("objective"),
                    elapsed=row.get("elapsed", row.get("parent_elapsed")),
                    error=row.get("error"),
                )
            )

    summary = _summarize(rows, args.wall_margin)
    _write_outputs(out_dir, rows, summary, args)
    print(f"[repeat] summary: {out_dir / 'summary.md'}")

    any_fail = any(item["fail_count"] for item in summary)
    margin_fail = any(not item["wall_margin_ok"] for item in summary)
    if any_fail or (args.strict_margin and margin_fail):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
