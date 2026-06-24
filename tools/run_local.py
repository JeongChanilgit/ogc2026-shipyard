"""Run a solver locally on a single instance with a hard time limit.

Usage:
    python tools/run_local.py instances/example/example_B2_b10.json --timelimit 60

The script:
  1. Loads the JSON instance.
  2. Imports `algorithm` from src/myalgorithm.py.
  3. Calls algorithm(prob_info, timelimit) with wall-clock timing.
  4. Validates the result with src/utils.check_feasibility.
  5. Prints feasibility stage, objective value, components Z1/Z2/Z3,
     elapsed time, and a per-objective contribution table.
  6. Optionally writes the raw solution and report to results/.

Exit code: 0 if PASS (feasible), 1 otherwise. Useful for CI / Makefile.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run OGC 2026 solver locally.")
    ap.add_argument("instance", help="Path to problem instance JSON")
    ap.add_argument("--timelimit", type=float, default=60.0,
                    help="Wall-clock seconds passed to algorithm() (default: 60)")
    ap.add_argument("--save", action="store_true",
                    help="Save solution + report under results/")
    ap.add_argument("--tag", default="local",
                    help="Tag for the saved run folder (default: local)")
    ap.add_argument("--trace", action="store_true",
                    help="Arm the analysis instrument (sets OGC_TRACE) -> results/traces/")
    ap.add_argument("--analyze", action="store_true",
                    help="Trace, then print tools/analyze_run.py report for this run")
    ap.add_argument("--plot", action="store_true",
                    help="With --analyze, also save an ALNS trajectory PNG")
    args = ap.parse_args()

    # Arm the tracer BEFORE importing the solver.  get_tracer() reads OGC_TRACE
    # at call time, so this is what switches src/instrument.py from NullTracer to
    # a real Tracer for this process only.
    import os
    if args.trace or args.analyze:
        os.environ.setdefault("OGC_TRACE", "1")
    trace_dir = ROOT / "results" / "traces"
    traces_before = set(trace_dir.glob("*.json")) if trace_dir.exists() else set()

    instance_path = Path(args.instance)
    if not instance_path.exists():
        print(f"[error] instance not found: {instance_path}")
        return 2

    with instance_path.open(encoding="utf-8") as f:
        prob_info = json.load(f)

    print(f"[run_local] instance: {instance_path.name}")
    print(f"[run_local] bays: {len(prob_info['bays'])}  blocks: {len(prob_info['blocks'])}")
    print(f"[run_local] weights: {prob_info.get('weights')}")
    print(f"[run_local] timelimit: {args.timelimit}s")

    from myalgorithm import algorithm
    from utils import check_feasibility

    t0 = time.perf_counter()
    solution = algorithm(prob_info, args.timelimit)
    elapsed = time.perf_counter() - t0

    print(f"[run_local] algorithm() returned in {elapsed:.2f}s")

    if not isinstance(solution, dict) or "operations" not in solution:
        print("[error] solution is not a dict with 'operations' key")
        return 1

    n_ops = sum(len(v) for v in solution["operations"].values())
    n_days = len(solution["operations"])
    print(f"[run_local] solution: {n_days} days, {n_ops} operations")

    report = check_feasibility(prob_info, solution)
    print()
    print(f"  feasible : {report['feasible']}")
    print(f"  stage    : {report['stage']}")
    if report["objective"] is not None:
        w = prob_info.get("weights", {})
        z1, z2, z3 = report["obj1"], report["obj2"], report["obj3"]
        w1, w2, w3 = w.get("w1", 1), w.get("w2", 1), w.get("w3", 1)
        print(f"  Z1 (tardiness)    : {z1:.2f}    × w1 {w1} = {w1*z1:,.2f}")
        print(f"  Z2 (imbalance)    : {z2:.2f}    × w2 {w2} = {w2*z2:,.2f}")
        print(f"  Z3 (pref penalty) : {z3:.2f}    × w3 {w3} = {w3*z3:,.2f}")
        print(f"  objective         : {report['objective']:,.2f}")
    if report["violations"]:
        print()
        print("  Violations:")
        for v in report["violations"][:10]:
            print(f"    - {v}")
        if len(report["violations"]) > 10:
            print(f"    ... ({len(report['violations']) - 10} more)")

    if args.save:
        out_dir = ROOT / "results" / f"{args.tag}_{instance_path.stem}_{int(time.time())}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "solution.json").write_text(json.dumps(solution, indent=2), encoding="utf-8")
        report_save = {**report, "elapsed_sec": elapsed, "instance": instance_path.name,
                       "timelimit": args.timelimit}
        (out_dir / "report.json").write_text(json.dumps(report_save, indent=2,
                                                        default=str), encoding="utf-8")
        print(f"\n  saved to: {out_dir}")

    # --- Analysis instrument: locate this run's trace, optionally analyze it ---
    if args.trace or args.analyze:
        traces_after = set(trace_dir.glob("*.json")) if trace_dir.exists() else set()
        new_traces = traces_after - traces_before
        trace_path = max(new_traces, key=lambda p: p.stat().st_mtime) if new_traces else None
        if trace_path is None:
            print("\n[run_local] no trace was written (instrument disabled?).")
        else:
            print(f"\n[run_local] trace: {trace_path.relative_to(ROOT)}")
            if args.analyze:
                import analyze_run
                v = analyze_run.RunView(analyze_run.load_trace(trace_path),
                                        source=str(trace_path.relative_to(ROOT)))
                findings = analyze_run.diagnose(v)
                plot_rel = None
                if args.plot:
                    plot_rel = analyze_run.make_plot(
                        v, analyze_run.FIG_DIR /
                        f"traj_{v.meta.get('instance', 'run')}_{int(time.time())}.png")
                md_report = analyze_run.render_report(v, findings, plot_rel)
                analyze_run.REPORT_DIR.mkdir(parents=True, exist_ok=True)
                safe = "".join(c if c.isalnum() or c in "._-" else "_"
                               for c in str(v.meta.get("instance", "run")))[:60]
                out = analyze_run.REPORT_DIR / f"report_{safe}_{int(time.time())}.md"
                out.write_text(md_report, encoding="utf-8")
                try:
                    print("\n" + md_report)
                except UnicodeEncodeError:
                    print("\n" + md_report.encode("ascii", "replace").decode("ascii"))
                print(f"\n[run_local] report saved: {out.relative_to(ROOT)}")

    return 0 if report["feasible"] else 1


if __name__ == "__main__":
    sys.exit(main())
