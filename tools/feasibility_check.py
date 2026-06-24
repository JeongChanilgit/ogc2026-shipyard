"""Standalone feasibility check for a saved solution.

Usage:
    python tools/feasibility_check.py results/<run>/solution.json instances/example/example_B2_b10.json

Loads both JSONs, calls utils.check_feasibility, prints the report.
Exits 0 on PASS, 1 on FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from utils import check_feasibility


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("solution", help="solution.json path")
    ap.add_argument("instance", help="problem instance JSON path")
    args = ap.parse_args()

    with open(args.instance, encoding="utf-8") as f:
        prob_info = json.load(f)
    with open(args.solution, encoding="utf-8") as f:
        solution = json.load(f)

    report = check_feasibility(prob_info, solution)
    print(json.dumps({k: v for k, v in report.items() if k != "violations"},
                     indent=2, default=str))
    if report["violations"]:
        print("\nViolations:")
        for v in report["violations"]:
            print(f"  - {v}")
    return 0 if report["feasible"] else 1


if __name__ == "__main__":
    sys.exit(main())
