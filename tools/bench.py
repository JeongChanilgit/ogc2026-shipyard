"""
bench.py -- Benchmark harness comparing baseline vs our solver on a set of instances.

Usage:
    python tools/bench.py instances/gen --timelimit 60
    python tools/bench.py instances/example --timelimit 30

Outputs:
  - CSV:      results/bench_<timestamp>.csv
  - Stdout:   Markdown summary table
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def _run_solver(solver_fn, prob_info: dict, timelimit: float) -> dict:
    """Run solver_fn and return a result dict with feasibility / timing info."""
    result = {
        "feasible": False,
        "objective": None,
        "obj1": None,
        "obj2": None,
        "obj3": None,
        "elapsed": None,
        "error": None,
    }
    try:
        t0 = time.perf_counter()
        solution = solver_fn(prob_info, timelimit)
        elapsed = time.perf_counter() - t0
        result["elapsed"] = elapsed

        from utils import check_feasibility
        report = check_feasibility(prob_info, solution)
        result["feasible"] = bool(report.get("feasible", False))
        result["objective"] = report.get("objective")
        result["obj1"] = report.get("obj1")
        result["obj2"] = report.get("obj2")
        result["obj3"] = report.get("obj3")
    except Exception as exc:
        result["error"] = str(exc)
        if result["elapsed"] is None:
            result["elapsed"] = 0.0
    return result


def _fmt(val, digits=4) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.{digits}f}"
    return str(val)


def _pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1f}%"


def run_bench(instances_dir: Path, timelimit: float) -> int:
    from baseline_greedy import greedyalgorithm
    from myalgorithm import algorithm

    instance_paths = sorted(instances_dir.glob("**/*.json"))
    if not instance_paths:
        print(f"[bench] No JSON files found in {instances_dir}")
        return 1

    print(f"[bench] Found {len(instance_paths)} instance(s) in {instances_dir}")
    print(f"[bench] timelimit={timelimit}s per solver per instance\n")

    rows = []

    for inst_path in instance_paths:
        with inst_path.open(encoding="utf-8") as f:
            prob_info = json.load(f)

        n_blocks = len(prob_info.get("blocks", []))
        n_bays = len(prob_info.get("bays", []))
        inst_name = inst_path.stem

        print(f"  {inst_name} (n={n_blocks}, m={n_bays}) ...", end="", flush=True)

        # Run baseline
        base_res = _run_solver(greedyalgorithm, prob_info, timelimit)
        # Run ours
        ours_res = _run_solver(algorithm, prob_info, timelimit)

        # Compute improvement
        b_obj = base_res["objective"]
        o_obj = ours_res["objective"]
        improvement = None
        improvement_pct = None
        if b_obj is not None and o_obj is not None:
            improvement = b_obj - o_obj
            if abs(b_obj) > 1e-9:
                improvement_pct = 100.0 * improvement / b_obj
            else:
                improvement_pct = 0.0

        row = {
            "instance": inst_name,
            "n": n_blocks,
            "m": n_bays,
            "timelimit": timelimit,
            # baseline
            "baseline_feasible": base_res["feasible"],
            "baseline_obj": base_res["objective"],
            "baseline_z1": base_res["obj1"],
            "baseline_z2": base_res["obj2"],
            "baseline_z3": base_res["obj3"],
            "baseline_elapsed": base_res["elapsed"],
            "baseline_error": base_res["error"],
            # ours
            "ours_feasible": ours_res["feasible"],
            "ours_obj": ours_res["objective"],
            "ours_z1": ours_res["obj1"],
            "ours_z2": ours_res["obj2"],
            "ours_z3": ours_res["obj3"],
            "ours_elapsed": ours_res["elapsed"],
            "ours_error": ours_res["error"],
            # comparison
            "improvement": improvement,
            "improvement_pct": improvement_pct,
        }
        rows.append(row)

        status_b = "OK" if base_res["feasible"] else "INFEAS"
        status_o = "OK" if ours_res["feasible"] else "INFEAS"
        print(f" baseline={status_b}({_fmt(b_obj, 2)}) ours={status_o}({_fmt(o_obj, 2)}) "
              f"improv={_pct(improvement_pct)} "
              f"({base_res['elapsed']:.1f}s/{ours_res['elapsed']:.1f}s)")

    # ------------------------------------------------------------------
    # Save CSV
    # ------------------------------------------------------------------
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = results_dir / f"bench_{timestamp}.csv"

    fieldnames = [
        "instance", "n", "m", "timelimit",
        "baseline_feasible", "baseline_obj", "baseline_z1", "baseline_z2", "baseline_z3",
        "baseline_elapsed", "baseline_error",
        "ours_feasible", "ours_obj", "ours_z1", "ours_z2", "ours_z3",
        "ours_elapsed", "ours_error",
        "improvement", "improvement_pct",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as cf:
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[bench] CSV saved: {csv_path}")

    # ------------------------------------------------------------------
    # Markdown summary
    # ------------------------------------------------------------------
    n_feasible_base = sum(1 for r in rows if r["baseline_feasible"])
    n_feasible_ours = sum(1 for r in rows if r["ours_feasible"])
    n_timeout_base = sum(1 for r in rows
                         if r["baseline_elapsed"] is not None
                         and r["baseline_elapsed"] > 0.85 * timelimit)
    n_timeout_ours = sum(1 for r in rows
                         if r["ours_elapsed"] is not None
                         and r["ours_elapsed"] > 0.85 * timelimit)

    valid_improvements = [r["improvement_pct"] for r in rows
                          if r["improvement_pct"] is not None]
    mean_improv = sum(valid_improvements) / len(valid_improvements) if valid_improvements else None

    print()
    print("## Benchmark Summary")
    print()
    # Header
    col_w = [30, 6, 5, 12, 12, 12, 12]
    hdr = (f"{'Instance':<{col_w[0]}} {'n':>{col_w[1]}} {'m':>{col_w[2]}} "
           f"{'Base Obj':>{col_w[3]}} {'Ours Obj':>{col_w[4]}} "
           f"{'Improv':>{col_w[5]}} {'ImprovPct':>{col_w[6]}}")
    sep = "-" * len(hdr)
    print(hdr)
    print(sep)
    for r in rows:
        line = (f"{r['instance']:<{col_w[0]}} "
                f"{r['n']:>{col_w[1]}} "
                f"{r['m']:>{col_w[2]}} "
                f"{_fmt(r['baseline_obj'], 2):>{col_w[3]}} "
                f"{_fmt(r['ours_obj'], 2):>{col_w[4]}} "
                f"{_fmt(r['improvement'], 2):>{col_w[5]}} "
                f"{_pct(r['improvement_pct']):>{col_w[6]}}")
        print(line)
    print(sep)
    print(f"\nAggregate ({len(rows)} instances):")
    print(f"  Baseline feasible rate : {n_feasible_base}/{len(rows)}")
    print(f"  Ours feasible rate     : {n_feasible_ours}/{len(rows)}")
    print(f"  Baseline timeouts      : {n_timeout_base}")
    print(f"  Ours timeouts          : {n_timeout_ours}")
    if mean_improv is not None:
        print(f"  Mean improvement %%     : {mean_improv:.2f}%%")
    print()

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark baseline vs our solver.")
    ap.add_argument("instances_dir", help="Directory containing *.json instances")
    ap.add_argument("--timelimit", type=float, default=60.0,
                    help="Wall-clock seconds per solver call (default: 60)")
    args = ap.parse_args()

    return run_bench(Path(args.instances_dir), args.timelimit)


if __name__ == "__main__":
    sys.exit(main())
