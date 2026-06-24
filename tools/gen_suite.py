"""
gen_suite.py -- Generate and validate the standard OGC 2026 instance suite.

Generates >=15 instances under instances/gen/ covering:
  - Sizes: small (n≈10), mid (n≈40), large (n≈120)
  - Packing: loose (density=0.20), tight (density=0.35)
  - Regime: w1-dom, w2-dom, w3-dom

After generation, runs baseline on each instance and reports PASS/FAIL.

Usage:
    python tools/gen_suite.py [--timelimit 30] [--skip-verify]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
GEN_DIR = ROOT / "instances" / "gen"
sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Suite specification: (filename_stem, n, m, density, regime, tightness, seed)
# ---------------------------------------------------------------------------
SUITE = [
    # --- small / loose ---
    ("gen_n10_loose_w1_s1",  10, 2, 0.20, "w1", 0.8, 1),
    ("gen_n10_loose_w2_s2",  10, 2, 0.20, "w2", 0.8, 2),
    ("gen_n10_loose_w3_s3",  10, 2, 0.20, "w3", 0.8, 3),

    # --- small / tight ---
    ("gen_n10_tight_w1_s4",  10, 2, 0.30, "w1", 0.3, 4),
    ("gen_n10_tight_w2_s5",  10, 2, 0.30, "w2", 0.3, 5),

    # --- mid / loose ---
    ("gen_n40_loose_w1_s6",  40, 3, 0.18, "w1", 0.8, 6),
    ("gen_n40_loose_w2_s7",  40, 3, 0.18, "w2", 0.8, 7),
    ("gen_n40_loose_w3_s8",  40, 3, 0.18, "w3", 0.8, 8),

    # --- mid / tight ---
    ("gen_n40_tight_w1_s9",  40, 3, 0.28, "w1", 0.3, 9),
    ("gen_n40_tight_w3_s10", 40, 3, 0.28, "w3", 0.3, 10),

    # --- large / loose ---
    ("gen_n120_loose_w1_s11", 120, 4, 0.14, "w1", 0.8, 11),
    ("gen_n120_loose_w2_s12", 120, 4, 0.14, "w2", 0.8, 12),
    ("gen_n120_loose_w3_s13", 120, 4, 0.14, "w3", 0.8, 13),

    # --- large / tight ---
    ("gen_n120_tight_w1_s14", 120, 4, 0.22, "w1", 0.3, 14),
    ("gen_n120_tight_w2_s15", 120, 4, 0.22, "w2", 0.3, 15),

    # --- extra: mid/loose for variety ---
    ("gen_n40_loose_w1_s16",  40, 2, 0.18, "w1", 0.6, 16),
    ("gen_n40_loose_w3_s17",  40, 4, 0.15, "w3", 0.7, 17),
]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--timelimit", type=float, default=30.0,
                    help="Baseline timelimit per instance for verification")
    ap.add_argument("--skip-verify", action="store_true",
                    help="Skip baseline verification (just generate)")
    args = ap.parse_args()

    # Import generation function
    tools_dir = ROOT / "tools"
    sys.path.insert(0, str(tools_dir))
    from gen_instance import generate_instance, validate_instance

    GEN_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(SUITE)} instances into {GEN_DIR}\n")

    gen_ok = 0
    gen_fail = 0
    for spec in SUITE:
        name, n, m, density, regime, tightness, seed = spec
        out_path = GEN_DIR / f"{name}.json"
        prob_info = generate_instance(
            n=n, m=m, density=density, regime=regime,
            tightness=tightness, max_layers=2, seed=seed,
        )
        errors = validate_instance(prob_info)
        if errors:
            print(f"  [SCHEMA-FAIL] {name}: {errors[:2]}")
            gen_fail += 1
            continue
        out_path.write_text(json.dumps(prob_info, indent=2), encoding="utf-8")
        print(f"  [GEN-OK] {name} (n={n}, m={m}, density={density}, {regime}, t={tightness})")
        gen_ok += 1

    print(f"\nGenerated: {gen_ok} OK, {gen_fail} FAIL\n")

    if args.skip_verify:
        print("Skipping baseline verification (--skip-verify).")
        return 0 if gen_fail == 0 else 1

    # ------------------------------------------------------------------
    # Verification: run baseline on each generated instance
    # ------------------------------------------------------------------
    from baseline_greedy import greedyalgorithm
    from utils import check_feasibility

    print(f"Verifying with baseline (timelimit={args.timelimit}s each)...\n")

    all_json = sorted(GEN_DIR.glob("*.json"))
    pass_count = 0
    fail_count = 0
    fail_list = []

    for inst_path in all_json:
        with inst_path.open(encoding="utf-8") as f:
            prob_info = json.load(f)
        n_b = len(prob_info["blocks"])
        n_m = len(prob_info["bays"])
        t0 = time.perf_counter()
        try:
            sol = greedyalgorithm(prob_info, args.timelimit)
            elapsed = time.perf_counter() - t0
            report = check_feasibility(prob_info, sol)
            if report["feasible"]:
                print(f"  PASS  {inst_path.name:<45}  "
                      f"obj={report['objective']:.2f}  ({elapsed:.1f}s)")
                pass_count += 1
            else:
                print(f"  FAIL  {inst_path.name:<45}  "
                      f"stage={report['stage']} viol={report['violations'][:2]}  ({elapsed:.1f}s)")
                fail_count += 1
                fail_list.append(inst_path.name)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"  ERROR {inst_path.name:<45}  {exc}  ({elapsed:.1f}s)")
            fail_count += 1
            fail_list.append(inst_path.name)

    print(f"\n{'='*60}")
    print(f"Verification: {pass_count} PASS, {fail_count} FAIL")
    if fail_list:
        print("Failed instances:")
        for f in fail_list:
            print(f"  - {f}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
