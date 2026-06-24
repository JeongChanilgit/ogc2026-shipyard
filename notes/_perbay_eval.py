#!/usr/bin/env python
"""A/B eval harness: OGC2026 solver with the per-bay engine OFF vs ON.

Runs each train instance twice in-process (OGC_PERBAY="0" then "1"), reporting
per-instance objective / feasibility / wall-time and totals, so per-bay tweaks
can be validated quickly.

Run with the env python DIRECTLY (NOT `conda run` -- it crashes with the
4-worker CP-SAT):

    C:/Users/peter/anaconda3/envs/ogc2025/python.exe notes/_perbay_eval.py \
        --instances prob_13,prob_14,prob_20,prob_3,prob_11 --timelimit 120

`--instances` accepts a comma list (prob_13,prob_14,...) or a keyword
SET1 / SET2 / ALL40.  Default = a fast representative subset (tardy/slow set1
plus a couple z1=0 ones to catch regressions).

OGC_PERBAY is read INLINE inside algorithm() (via _env_on), so flipping
os.environ before each call takes effect -- do NOT re-import myalgorithm.
NOTE: perbay defaults to ON, so the baseline leg MUST set OGC_PERBAY="0".
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
TRAIN = os.path.join(ROOT, "instances", "train")

# Make `import myalgorithm` and `import utils` resolve to src/.  Pin src FIRST.
sys.path.insert(0, SRC)

# Optional 4-core affinity (mirrors notes/_capture20_aff.py).  Best-effort.
def _pin_affinity(n=4):
    try:
        import psutil
        p = psutil.Process()
        avail = p.cpu_affinity()
        if avail and len(avail) > n:
            p.cpu_affinity(avail[:n])
    except Exception:
        pass


def _resolve_instances(spec):
    """Expand the --instances spec into a list of existing prob_* base names."""
    def exists(name):
        return os.path.isfile(os.path.join(TRAIN, name + ".json"))

    spec = (spec or "").strip()
    up = spec.upper()
    if up == "SET1":
        cand = [f"prob_{i}" for i in range(1, 21)]
    elif up == "SET2":
        cand = [f"prob_{i}" for i in range(21, 41)]
    elif up == "ALL40":
        cand = [f"prob_{i}" for i in range(1, 41)]
    else:
        cand = [s.strip() for s in spec.split(",") if s.strip()]

    out, missing = [], []
    for name in cand:
        (out if exists(name) else missing).append(name)
    if missing:
        print(f"[warn] skipping non-existent instances: {', '.join(missing)}",
              flush=True)
    return out


def _load(name):
    with open(os.path.join(TRAIN, name + ".json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _run_leg(algorithm, check_feasibility, prob_info, tl, perbay):
    """Run one solver leg with OGC_PERBAY set; return (obj_or_None, feas, wall, status)."""
    os.environ["OGC_PERBAY"] = "1" if perbay else "0"
    t0 = time.monotonic()
    try:
        sol = algorithm(prob_info, tl)
    except Exception as e:
        wall = time.monotonic() - t0
        return None, False, wall, f"CRASH:{type(e).__name__}"
    wall = time.monotonic() - t0
    try:
        chk = check_feasibility(prob_info, sol)
        feas = bool(chk.get("feasible"))
        obj = float(chk["objective"]) if feas and chk.get("objective") is not None else None
        return obj, feas, wall, ("OK" if feas else "INFEASIBLE")
    except Exception as e:
        return None, False, wall, f"CHECK_ERR:{type(e).__name__}"


def _fmt_obj(obj, status):
    if status.startswith("CRASH"):
        return "CRASH"
    if obj is None:
        return "INFEAS"
    return f"{obj:,.0f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--instances",
        default="prob_13,prob_14,prob_20,prob_3,prob_11",
        help="comma list (prob_13,prob_14,...) or SET1 / SET2 / ALL40",
    )
    ap.add_argument("--timelimit", type=float, default=120.0)
    args = ap.parse_args()

    _pin_affinity(4)

    instances = _resolve_instances(args.instances)
    if not instances:
        print("[error] no valid instances to run", flush=True)
        return 2

    TL = args.timelimit
    print(f"# perbay A/B eval  TL={TL:g}s  instances={','.join(instances)}",
          flush=True)
    print(f"# python={sys.executable}", flush=True)

    # Import ONCE -- never re-import between runs (some flags cache at import,
    # but OGC_PERBAY is read inline so per-call env works).
    import myalgorithm
    from utils import check_feasibility
    algorithm = myalgorithm.algorithm

    hdr = (f"{'instance':<10} | {'base_obj':>14} {'feas':>6} {'wall':>7} | "
           f"{'pb_obj':>14} {'feas':>6} {'wall':>7} | {'delta':>14} {'delta%':>8} | flag")
    sep = "-" * len(hdr)
    print(sep, flush=True)
    print(hdr, flush=True)
    print(sep, flush=True)

    rows = []
    max_wall = 0.0
    for name in instances:
        try:
            prob_info = _load(name)
        except Exception as e:
            print(f"{name:<10} | LOAD ERROR: {type(e).__name__}: {e}", flush=True)
            rows.append({"name": name, "load_err": True})
            continue

        b_obj, b_feas, b_wall, b_st = _run_leg(
            algorithm, check_feasibility, prob_info, TL, perbay=False)
        # reload to avoid any cross-leg mutation of prob_info
        prob_info = _load(name)
        p_obj, p_feas, p_wall, p_st = _run_leg(
            algorithm, check_feasibility, prob_info, TL, perbay=True)

        max_wall = max(max_wall, b_wall, p_wall)

        both_feas = (b_obj is not None) and (p_obj is not None)
        if both_feas:
            delta = p_obj - b_obj
            dpct = (delta / b_obj * 100.0) if b_obj != 0 else 0.0
            if delta < -1e-9:
                flag = "WIN"
            elif delta > 1e-9:
                flag = "REGRESS <<<"
            else:
                flag = "tie"
            delta_s = f"{delta:,.0f}"
            dpct_s = f"{dpct:+.2f}%"
        else:
            delta = None
            flag = "EXCLUDED(infeas/crash)"
            delta_s = "-"
            dpct_s = "-"

        print(
            f"{name:<10} | {_fmt_obj(b_obj, b_st):>14} {str(b_feas):>6} "
            f"{b_wall:>6.1f}s | {_fmt_obj(p_obj, p_st):>14} {str(p_feas):>6} "
            f"{p_wall:>6.1f}s | {delta_s:>14} {dpct_s:>8} | {flag}",
            flush=True,
        )
        rows.append({
            "name": name, "b_obj": b_obj, "b_feas": b_feas, "b_wall": b_wall,
            "b_st": b_st, "p_obj": p_obj, "p_feas": p_feas, "p_wall": p_wall,
            "p_st": p_st, "both_feas": both_feas, "delta": delta,
        })

    print(sep, flush=True)

    # Totals over instances feasible in BOTH legs only.
    both = [r for r in rows if r.get("both_feas")]
    excluded = [r["name"] for r in rows
                if not r.get("both_feas") and not r.get("load_err")]
    base_sum = sum(r["b_obj"] for r in both)
    pb_sum = sum(r["p_obj"] for r in both)
    tot_delta = pb_sum - base_sum
    tot_pct = (tot_delta / base_sum * 100.0) if base_sum != 0 else 0.0

    wins = sum(1 for r in both if r["delta"] < -1e-9)
    ties = sum(1 for r in both if abs(r["delta"]) <= 1e-9)
    regs = sum(1 for r in both if r["delta"] > 1e-9)

    print(f"# totals over {len(both)} instance(s) feasible in BOTH legs:", flush=True)
    print(f"#   base_sum = {base_sum:,.0f}", flush=True)
    print(f"#   pb_sum   = {pb_sum:,.0f}", flush=True)
    print(f"#   delta    = {tot_delta:,.0f}  ({tot_pct:+.2f}%)", flush=True)
    print(f"#   wins={wins}  ties={ties}  regressions={regs}", flush=True)
    if excluded:
        print(f"#   EXCLUDED (infeasible/crash in >=1 leg): {', '.join(excluded)}",
              flush=True)
    print(f"#   max_wall = {max_wall:.1f}s  (TL={TL:g}s; "
          f"{'OK <= TL' if max_wall <= TL + 1e-6 else 'OVER TL <<<'})", flush=True)

    # Never-(-1) sanity: any infeasible leg is a hard problem.
    infeas_legs = [
        (r["name"], leg)
        for r in rows if not r.get("load_err")
        for leg, ok in (("base", r["b_feas"]), ("perbay", r["p_feas"]))
        if not ok
    ]
    if infeas_legs:
        print("#   WARNING infeasible legs (would score -1): "
              + ", ".join(f"{n}/{leg}" for n, leg in infeas_legs), flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
