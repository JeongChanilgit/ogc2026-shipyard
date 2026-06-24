#!/usr/bin/env python3
"""
resequence_gain.py -- READ-ONLY analysis (imports the solver decoder; edits nothing).

Goal
----
Quantify the REALIZABLE (feasible, non-myopic) Z1/tardiness reduction available
from better PER-BAY DECODE SEQUENCING alone -- holding the block->bay assignment
fixed (same as the base solution).  Re-sequencing the blocks within ONE bay only
changes that bay's entry/exit times -> only Z1; Z2/Z3 and every other bay are
untouched.  The solver's per-bay decoder (`_decode_bay` via `_find_slot_crane_safe`)
guarantees crane-safe + collision-free placement, so EVERY decoded schedule it
returns is FEASIBLE by construction.

Method (per instance, per bay j with current tardiness > 0)
-----------------------------------------------------------
current_tard_j = sum of CURRENT tardiness of blocks assigned to j in the base sol.
Candidate orderings of j's assigned block_ids:
    - all of `_orderings(...)` output (EDD/release-then-due/ATCR, ATCR forced on)
    - EDD-by-(due, release)
    - SPT (processing-time ascending)
    - ~200 random shuffles
    - a pairwise-swap local search (budget ~500 evals) seeded from best heuristic
For each ordering: `_decode_bay` -> resulting exits -> bay tardiness.
best_tard_j = min over orderings; record which ORDERING-TYPE produced the best.
gain_j = max(0, current_tard_j - best_tard_j).

Aggregate (over bays measured): current_Z1 = Sum current_tard_j,
best_Z1 = Sum best_tard_j, realizable_reduction = current_Z1 - best_Z1,
pct = 100 * reduction / current_Z1.

SANITY self-check: re-decode each bay using the SOLUTION's OWN ENTRY-time ordering;
the resulting bay tardiness should ~reproduce current_tard_j (the base solver used
the same decoder).  Mismatch means the decode call is wrong.
"""

import os
import sys
import json
import time
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Force ATCR seed ON so `_orderings` also emits the ATCR candidate.
os.environ.setdefault("OGC_ATCR_SEED", "1")
# Crane-safe decode ON (the solver default) -> every decoded schedule is feasible.
os.environ.setdefault("OGC_CRANE_SAFE", "1")

from utils import Bay                                              # noqa: E402
from myalgorithm import _decode_bay, _orderings, _bay_tardiness   # noqa: E402

INSTANCES = ["prob_6", "prob_11", "prob_14", "prob_16", "prob_20"]
INST_DIR = ROOT / "instances" / "train"
SOL_DIR = ROOT / "results" / "z1_exp_B"

N_RANDOM = 200          # random shuffles per bay (CAPPED by per-bay time budget)
LS_BUDGET = 500         # pairwise-swap local-search decode evals (CAPPED by budget)
SEED = 12345

# REALITY CHECK: these base solutions pack ~150 blocks into ~3 huge bays, and the
# crane-safe decode is O(positions x orientations) Shapely -> a single decode of a
# 56-block bay costs ~60s.  200 shuffles + 500 LS evals would be ~12h PER BAY.  So
# every decode is gated by a per-bay wall-clock budget: the (cheap, meaningful)
# heuristic orderings always run; random shuffles + swap LS only consume whatever
# budget remains.  Small bays get many evals; a giant bay gets the heuristics only.
PER_BAY_BUDGET_S = 90.0   # wall-clock seconds for random+LS exploration per bay
PER_INST_BUDGET_S = 600.0 # hard ceiling per instance (heuristics still always run)


def load_solution_blocks(sol):
    """block_id -> {bay, x, y, orient, entry, exit} from the operations stream."""
    rec = {}
    for t_str, ops in sol["operations"].items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            r = rec.setdefault(bid, {})
            if op["type"] == "ENTRY":
                r["bay"] = op["bay_id"]
                r["x"] = op["x"]
                r["y"] = op["y"]
                r["orient"] = op["orient_idx"]
                r["entry"] = t
            elif op["type"] == "EXIT":
                r["exit"] = t
    return rec


def decode_tard(bay, bay_idx, order, blocks_data):
    """Decode one ordering -> bay tardiness (math.inf if a block cannot fit)."""
    res, _forced = _decode_bay(bay, bay_idx, list(order), blocks_data)
    if res is None:
        return float("inf"), None
    return _bay_tardiness(res, blocks_data), res


def heuristic_orderings(ids, blocks_data):
    """The cheap, MEANINGFUL candidate orderings -- always evaluated."""
    out = []
    # --- the solver's own heuristic orderings (EDD / release-then-due / ATCR) ---
    base = _orderings(list(ids), blocks_data, allow_alt=True)
    labels = ["EDD"]
    if len(base) >= 2:
        labels.append("REL")
    if len(base) >= 3:
        labels.append("ATCR")
    for lab, order in zip(labels, base):
        out.append((lab, order))
    # --- EDD-by-(due, release) ---
    out.append(("EDD_dr", sorted(ids, key=lambda b: (blocks_data[b]["due_date"],
                                                      blocks_data[b]["release_time"]))))
    # --- SPT (processing ascending) ---
    out.append(("SPT", sorted(ids, key=lambda b: blocks_data[b]["processing_time"])))
    return out


def random_search(ids, bay, bay_idx, blocks_data, deadline, rng):
    """Decode random shuffles until N_RANDOM done OR wall-clock deadline hit.
    Returns (best_tard, best_order, n_evals)."""
    best_tard = float("inf")
    best_order = None
    n = 0
    for _ in range(N_RANDOM):
        if time.monotonic() > deadline:
            break
        sh = list(ids)
        rng.shuffle(sh)
        t, _ = decode_tard(bay, bay_idx, sh, blocks_data)
        n += 1
        if t < best_tard:
            best_tard = t
            best_order = sh
    return best_tard, best_order, n


def local_search(seed_order, bay, bay_idx, blocks_data, seed_tard, budget, deadline):
    """Pairwise-swap hill-climb seeded from `seed_order`; returns (tard, order, evals).
    Bounded by BOTH a decode-eval budget AND a wall-clock deadline (decode is slow)."""
    cur = list(seed_order)
    cur_tard = seed_tard
    n = len(cur)
    evals = 0
    improved = True
    while improved and evals < budget and time.monotonic() < deadline:
        improved = False
        for i in range(n):
            for k in range(i + 1, n):
                if evals >= budget or time.monotonic() > deadline:
                    break
                cur[i], cur[k] = cur[k], cur[i]
                t, _ = decode_tard(bay, bay_idx, cur, blocks_data)
                evals += 1
                if t < cur_tard - 1e-9:
                    cur_tard = t
                    improved = True
                else:
                    cur[i], cur[k] = cur[k], cur[i]  # revert
            if evals >= budget or time.monotonic() > deadline:
                break
    return cur_tard, cur, evals


def analyze_instance(inst_name, rng):
    inst = json.loads((INST_DIR / f"{inst_name}.json").read_text())
    sol = json.loads((SOL_DIR / f"sol_{inst_name}__base.json").read_text())
    blocks_data = inst["blocks"]
    bays = [Bay.from_dict(d, j) for j, d in enumerate(inst["bays"])]

    rec = load_solution_blocks(sol)

    # group block_ids by bay; compute current tardiness per block
    by_bay = {}          # bay_idx -> list of block_id
    cur_tard_block = {}  # block_id -> current tardiness
    for bid, r in rec.items():
        if "bay" not in r or "exit" not in r:
            continue
        bay_idx = r["bay"]
        by_bay.setdefault(bay_idx, []).append(bid)
        due = blocks_data[bid]["due_date"]
        cur_tard_block[bid] = max(0.0, r["exit"] - due)

    bays_measured = 0
    current_Z1 = 0.0
    best_Z1 = 0.0
    selfcheck_Z1 = 0.0          # re-decode using solution's own entry-order
    win_mix = {}                # ordering-type -> count of bays it won
    neg_clamped_bays = 0        # bays where best > current (clamped)
    tot_rand_evals = 0
    tot_ls_evals = 0
    budget_exhausted_bays = 0   # bays where the time budget cut exploration short

    t0 = time.monotonic()
    inst_deadline = t0 + PER_INST_BUDGET_S
    measured_bays = [(j, ids) for j, ids in by_bay.items()
                     if sum(cur_tard_block[b] for b in ids) > 0]
    n_meas = len(measured_bays)

    for n_done, (bay_idx, ids) in enumerate(measured_bays, 1):
        bay = bays[bay_idx]
        cur_t = sum(cur_tard_block[b] for b in ids)
        current_Z1 += cur_t
        bays_measured += 1

        # ---- self-check: re-decode in the solution's OWN entry-time order ----
        own_order = sorted(ids, key=lambda b: rec[b]["entry"])
        sc_tard, _ = decode_tard(bay, bay_idx, own_order, blocks_data)
        selfcheck_Z1 += (sc_tard if sc_tard != float("inf") else cur_t)

        # ---- evaluate the cheap, meaningful heuristic orderings (always) ----
        best_tard = float("inf")
        best_label = None
        best_order = None
        for lab, order in heuristic_orderings(ids, blocks_data):
            t, _ = decode_tard(bay, bay_idx, order, blocks_data)
            if t < best_tard:
                best_tard = t
                best_label = lab
                best_order = order

        # ---- budget-gated exploration: random shuffles, then swap LS ----
        # decode of a big bay can cost ~60s, so cap exploration by wall-clock.
        bay_deadline = min(time.monotonic() + PER_BAY_BUDGET_S, inst_deadline)
        rand_tard, rand_order, rand_n = random_search(
            ids, bay, bay_idx, blocks_data, bay_deadline, rng)
        tot_rand_evals += rand_n
        if rand_tard < best_tard - 1e-9:
            best_tard = rand_tard
            best_label = "RAND"
            best_order = rand_order

        if best_order is not None and len(ids) > 2 and time.monotonic() < bay_deadline:
            ls_tard, _ls_order, ls_n = local_search(
                best_order, bay, bay_idx, blocks_data, best_tard, LS_BUDGET, bay_deadline)
            tot_ls_evals += ls_n
            if ls_tard < best_tard - 1e-9:
                best_tard = ls_tard
                best_label = "LS"

        # diagnostic: did we run out of budget before fully exploring this bay?
        if rand_n < N_RANDOM:
            budget_exhausted_bays += 1

        if best_tard == float("inf"):
            best_tard = cur_t  # decode failed for all orders: no gain claimed

        gain = cur_t - best_tard
        if gain < 0:
            neg_clamped_bays += 1
            best_tard = cur_t  # clamp: never claim a loss
            gain = 0.0

        best_Z1 += best_tard
        win_mix[best_label] = win_mix.get(best_label, 0) + 1

        print(f"  [{inst_name}] bay {n_done}/{n_meas} (idx {bay_idx}, "
              f"n={len(ids)}): cur={cur_t:.0f} best={best_tard:.0f} "
              f"win={best_label} rand_evals={rand_n} "
              f"({time.monotonic()-t0:.1f}s)", flush=True)

    reduction = current_Z1 - best_Z1
    pct = (100.0 * reduction / current_Z1) if current_Z1 > 0 else 0.0
    # self-check error: how far the own-order re-decode drifts from current
    sc_err = abs(selfcheck_Z1 - current_Z1)
    sc_pct = (100.0 * sc_err / current_Z1) if current_Z1 > 0 else 0.0

    return {
        "inst": inst_name,
        "bays_measured": bays_measured,
        "current_Z1": current_Z1,
        "best_Z1": best_Z1,
        "reduction": reduction,
        "pct": pct,
        "win_mix": win_mix,
        "selfcheck_Z1": selfcheck_Z1,
        "selfcheck_err": sc_err,
        "selfcheck_pct": sc_pct,
        "neg_clamped_bays": neg_clamped_bays,
        "tot_rand_evals": tot_rand_evals,
        "tot_ls_evals": tot_ls_evals,
        "budget_exhausted_bays": budget_exhausted_bays,
    }


def fmt_mix(mix):
    return ",".join(f"{k}:{v}" for k, v in sorted(mix.items(), key=lambda kv: -kv[1]))


def main():
    rng = random.Random(SEED)
    results = []
    for inst in INSTANCES:
        print(f"== analyzing {inst} ==", flush=True)
        results.append(analyze_instance(inst, rng))

    # ---- main table ----
    print("\n" + "=" * 118)
    print("PER-BAY RESEQUENCING Z1 HEADROOM (assignment fixed; only Z1 affected)")
    print("=" * 118)
    hdr = (f"{'inst':>8} | {'bays_meas':>9} | {'current_Z1':>12} | {'best_Z1':>12} | "
           f"{'reduction':>10} | {'pct_red':>8} | {'winning_ordering_mix':<28}")
    print(hdr)
    print("-" * 118)
    tot_cur = tot_best = 0.0
    for r in results:
        tot_cur += r["current_Z1"]
        tot_best += r["best_Z1"]
        print(f"{r['inst']:>8} | {r['bays_measured']:>9} | {r['current_Z1']:>12.0f} | "
              f"{r['best_Z1']:>12.0f} | {r['reduction']:>10.0f} | {r['pct']:>7.1f}% | "
              f"{fmt_mix(r['win_mix']):<28}")
    print("-" * 118)
    tot_red = tot_cur - tot_best
    tot_pct = (100.0 * tot_red / tot_cur) if tot_cur > 0 else 0.0
    print(f"{'ALL':>8} | {sum(r['bays_measured'] for r in results):>9} | "
          f"{tot_cur:>12.0f} | {tot_best:>12.0f} | {tot_red:>10.0f} | {tot_pct:>7.1f}% |")
    print("=" * 118)

    # ---- self-check table ----
    print("\nSELF-CHECK (re-decode bays in the SOLUTION's own entry order vs current):")
    print(f"{'inst':>8} | {'current_Z1':>12} | {'selfcheck_Z1':>12} | "
          f"{'abs_err':>10} | {'err_pct':>8} | {'neg_clamped_bays':>16}")
    for r in results:
        print(f"{r['inst']:>8} | {r['current_Z1']:>12.0f} | {r['selfcheck_Z1']:>12.0f} | "
              f"{r['selfcheck_err']:>10.0f} | {r['selfcheck_pct']:>7.1f}% | "
              f"{r['neg_clamped_bays']:>16}")

    # ---- exploration-depth diagnostic (how budget-starved was each instance) ----
    print("\nEXPLORATION DEPTH (budget-gated: big bays get heuristics only):")
    print(f"{'inst':>8} | {'rand_evals':>10} | {'ls_evals':>9} | "
          f"{'budget_starved_bays':>19} (of bays_measured)")
    for r in results:
        print(f"{r['inst']:>8} | {r['tot_rand_evals']:>10} | {r['tot_ls_evals']:>9} | "
              f"{r['budget_exhausted_bays']:>19} / {r['bays_measured']}")

    # ---- bottom line ----
    print("\n" + "=" * 118)
    verdict = "LARGE -- worth building a per-bay scheduler" if tot_pct >= 5.0 \
        else "SMALL -- Z1 is near the per-bay sequencing floor"
    print(f"BOTTOM LINE: realizable per-bay-sequencing Z1 reduction = "
          f"{tot_red:.0f} ({tot_pct:.1f}% of measured current_Z1) -> {verdict}")
    max_sc = max(r["selfcheck_pct"] for r in results)
    sc_ok = "OK (decode reproduces current within tolerance)" if max_sc < 2.0 \
        else "WARN -- own-order re-decode drifts from current; inspect decode call"
    print(f"SELF-CHECK: max own-order drift = {max_sc:.1f}% -> {sc_ok}")
    print("=" * 118)
    return results


if __name__ == "__main__":
    main()
