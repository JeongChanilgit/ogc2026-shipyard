"""Static (solver-free) per-instance structural analysis CLI for OGC2026.

Reads each train instance and reports purely structural diagnostics -- no solver
is run.  Builds on the shared analysis core in ``ogc_analysis.py`` (read-only).

What it tells you per instance:
  * size (n_blocks, n_bays) and objective weights (w1 dominates, ~3000x w2)
  * intrinsic Z1 lower bound (tardiness no schedule can avoid)
  * peak area-demand vs bay floor in two models:
      - bbox model  = what our conservative rectangle packer must fit
      - foot model  = what an exact-polygon packer could fit
    plus how many bays are over-capacity in each model and the bbox->foot gap
    (the exploitable rectangle-waste headroom: a large gap means exact-polygon
    packing could rescue a bay that the bbox packer calls over-capacity)
  * slack histogram over blocks (slack = due - release - processing): min,
    median, and % of "urgent" blocks (slack <= 2) that drive tardiness

The SUMMARY then splits instances into the Cat1/Cat2 feasibility classes:
  * AREA-FEASIBLE  : max foot-demand < 100% -> some packer can fit; tardiness is
                     a packing/sequencing artefact, not a hard area floor
  * OVER-CAPACITY  : max foot-demand >= 100% -> physically over-capacity for ANY
                     packer in some bay -> intrinsic serialisation/tardiness

Usage:
    python tools/inst_report.py                      # all train instances
    python tools/inst_report.py prob_13 prob_20      # only these
    python tools/inst_report.py --json results/x.json  # also dump JSON

All printed/written text is plain ASCII (Windows console is cp949).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ogc_analysis as A  # noqa: E402


def _round1(x):
    """Round to 1 decimal, passing through None."""
    return None if x is None else round(float(x), 1)


def analyze(name: str) -> dict:
    """Compute the static structural diagnostics for one instance."""
    prob = A.load_instance(name)
    blocks = prob["blocks"]
    bays = prob["bays"]
    weights = prob.get("weights", {})

    dp = A.demand_peak(prob)
    per_bay = dp["per_bay"]
    max_pct = dp["max_pct"]
    max_pct_foot = dp["max_pct_foot"]
    n_overcap_bbox = sum(1 for b in per_bay if b["pct"] > 100.0)
    n_overcap_foot = sum(1 for b in per_bay if b["pct_foot"] > 100.0)
    # Exploitable rectangle-waste headroom at the worst bay.
    bbox_foot_gap = max_pct - max_pct_foot

    z1_lb = A.intrinsic_z1_lb(prob)

    # Slack = due - release - processing, over all blocks.
    slacks = [b["due_date"] - b["release_time"] - b["processing_time"]
              for b in blocks]
    n = len(slacks)
    slack_min = min(slacks) if slacks else 0.0
    slack_med = statistics.median(slacks) if slacks else 0.0
    n_urgent = sum(1 for s in slacks if s <= 2)
    pct_urgent = (100.0 * n_urgent / n) if n else 0.0

    # foot < 100 => some packer can fit every bay; tardiness is a packing /
    # sequencing artefact, not a hard area floor (Cat1).  foot >= 100 => a bay
    # is physically over-capacity for ANY packer (Cat2).
    category = "OVER-CAPACITY" if max_pct_foot >= 100.0 else "AREA-FEASIBLE"

    return {
        "name": prob.get("name", name),
        "n_blocks": n,
        "n_bays": len(bays),
        "w1": weights.get("w1"),
        "w2": weights.get("w2"),
        "w3": weights.get("w3"),
        "z1_lb": _round1(z1_lb),
        "max_pct_bbox": _round1(max_pct),
        "max_pct_foot": _round1(max_pct_foot),
        "n_overcap_bbox": n_overcap_bbox,
        "n_overcap_foot": n_overcap_foot,
        "bbox_foot_gap": _round1(bbox_foot_gap),
        "slack_min": _round1(slack_min),
        "slack_med": _round1(slack_med),
        "n_urgent": n_urgent,
        "pct_urgent": _round1(pct_urgent),
        "category": category,
    }


# Column spec: (header, result-key, width).  Right-aligned numeric cols, the
# name is left-aligned (handled below).
_COLS = [
    ("name", "name", 10),
    ("nblk", "n_blocks", 5),
    ("nbay", "n_bays", 5),
    ("w1", "w1", 8),
    ("w2", "w2", 6),
    ("w3", "w3", 6),
    ("Z1_LB", "z1_lb", 9),
    ("bbox%", "max_pct_bbox", 8),
    ("foot%", "max_pct_foot", 8),
    ("ovB", "n_overcap_bbox", 4),
    ("ovF", "n_overcap_foot", 4),
    ("b-f_gap", "bbox_foot_gap", 9),
    ("slkMin", "slack_min", 8),
    ("slkMed", "slack_med", 8),
    ("urg%", "pct_urgent", 6),
]


def _fmt_cell(val, width, left=False):
    s = "" if val is None else str(val)
    return s.ljust(width) if left else s.rjust(width)


def print_table(results: list) -> None:
    header = "  ".join(
        _fmt_cell(h, w, left=(key == "name")) for (h, key, w) in _COLS)
    print(header)
    print("-" * len(header))
    for r in results:
        row = "  ".join(
            _fmt_cell(r.get(key), w, left=(key == "name"))
            for (h, key, w) in _COLS)
        print(row)


def print_summary(results: list) -> None:
    area_feasible = [r["name"] for r in results
                     if r["category"] == "AREA-FEASIBLE"]
    over_capacity = [r["name"] for r in results
                     if r["category"] == "OVER-CAPACITY"]
    print("")
    print("=" * 60)
    print("SUMMARY: Cat1/Cat2 feasibility split (by max foot-demand %)")
    print("=" * 60)
    print("")
    print("AREA-FEASIBLE (foot<100, bbox may be >100)  count=%d" %
          len(area_feasible))
    print("  some packer can fit every bay; tardiness is a packing/seq artefact")
    print("  " + (", ".join(area_feasible) if area_feasible else "(none)"))
    print("")
    print("OVER-CAPACITY (foot>=100)  count=%d" % len(over_capacity))
    print("  a bay is over-capacity for ANY packer -> intrinsic serialisation")
    print("  " + (", ".join(over_capacity) if over_capacity else "(none)"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Static per-instance structural analysis for OGC2026.")
    parser.add_argument("instances", nargs="*",
                        help="instance names (e.g. prob_13). Default: all.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write the full structured result as JSON.")
    args = parser.parse_args(argv)

    names = args.instances if args.instances else A.list_train_instances()

    results = []
    for name in names:
        try:
            results.append(analyze(name))
        except Exception as e:  # noqa: BLE001
            print("ERROR analyzing %s: %s" % (name, e), file=sys.stderr)

    print_table(results)
    print_summary(results)

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)),
                    exist_ok=True)
        out = {
            "instances": results,
            "summary": {
                "area_feasible": [r["name"] for r in results
                                  if r["category"] == "AREA-FEASIBLE"],
                "over_capacity": [r["name"] for r in results
                                  if r["category"] == "OVER-CAPACITY"],
            },
        }
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print("")
        print("wrote JSON: %s" % args.json_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
