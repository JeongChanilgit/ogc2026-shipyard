"""Run ONE solver on ONE instance in an isolated process, score with the
(new, eval-server-mirrored) check_feasibility, and emit a JSON result line.

Why a dedicated process per (instance, solver):
  * Our code and the official baseline both ship modules literally named
    ``utils`` and ``baseline_greedy``.  Importing both in one interpreter would
    collide in sys.modules.  One process per solver side-steps that entirely.
  * It also isolates crashes/timeouts the way the evaluation server does.

Usage:
    python tools/run_solver_once.py <instance.json> --solver our|baseline \
        --timelimit 60 [--out result.json]

Stdout: a single JSON object with feasibility, objective components, the
weighted score, and elapsed wall-clock.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Put src on sys.path at MODULE level (not inside main): our solver uses
# multiprocessing `spawn`, which re-imports this module in each child.  The
# children's worker fns do `from myalgorithm import ...`, so src must already be
# on sys.path when the module is imported -- exactly how run_local.py does it.
sys.path.insert(0, str(ROOT / "src"))


def _load_solver(solver: str):
    """Return (algorithm_fn, check_feasibility_fn) for the requested solver,
    with sys.path set so the matching utils/baseline_greedy resolve correctly."""
    if solver == "our":
        from myalgorithm import algorithm  # noqa: E402
        from utils import check_feasibility  # noqa: E402
        return algorithm, check_feasibility
    elif solver == "baseline":
        bdir = ROOT / "baseline" / "ogc2026" / "baseline"
        # Insert at 0 so the official baseline's utils/baseline_greedy take
        # precedence over the src/ copies (our baseline_greedy is a fork).
        # src/utils.py and baseline/utils.py are byte-identical (both synced to
        # the new official), so check_feasibility scores both solvers the same.
        sys.path.insert(0, str(bdir))
        import baseline_greedy  # noqa: E402
        from utils import check_feasibility  # noqa: E402

        def algorithm(prob_info, timelimit):
            return baseline_greedy.greedyalgorithm(prob_info, timelimit)

        return algorithm, check_feasibility
    else:
        raise ValueError(f"unknown solver: {solver}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance")
    ap.add_argument("--solver", choices=["our", "baseline"], required=True)
    ap.add_argument("--timelimit", type=float, default=60.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--save-sol", default=None,
                    help="If set, write the raw solution JSON to this path.")
    args = ap.parse_args()

    inst_path = Path(args.instance)
    prob_info = json.loads(inst_path.read_text(encoding="utf-8"))
    w = prob_info.get("weights", {}) or {}
    w1, w2, w3 = w.get("w1", 1), w.get("w2", 1), w.get("w3", 1)

    result = {
        "instance": inst_path.stem,
        "solver": args.solver,
        "timelimit": args.timelimit,
        "n_bays": len(prob_info.get("bays", [])),
        "n_blocks": len(prob_info.get("blocks", [])),
        "w1": w1, "w2": w2, "w3": w3,
    }

    try:
        algorithm, check_feasibility = _load_solver(args.solver)
        t0 = time.perf_counter()
        solution = algorithm(prob_info, args.timelimit)
        elapsed = time.perf_counter() - t0
        report = check_feasibility(prob_info, solution)
        if args.save_sol:
            Path(args.save_sol).write_text(
                json.dumps(solution, default=str), encoding="utf-8")
        result.update({
            "ok": True,
            "feasible": bool(report.get("feasible")),
            "stage": report.get("stage"),
            "obj1": report.get("obj1"),
            "obj2": report.get("obj2"),
            "obj3": report.get("obj3"),
            "objective": report.get("objective"),
            "elapsed": round(elapsed, 3),
            "n_violations": len(report.get("violations", []) or []),
            "first_violations": (report.get("violations", []) or [])[:3],
        })
    except Exception as e:  # never let a crash escape unlabeled
        result.update({
            "ok": False,
            "feasible": False,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-1500:],
        })

    line = json.dumps(result, default=str)
    print(line)
    if args.out:
        Path(args.out).write_text(line, encoding="utf-8")
    return 0 if result.get("feasible") else 1


if __name__ == "__main__":
    sys.exit(main())
