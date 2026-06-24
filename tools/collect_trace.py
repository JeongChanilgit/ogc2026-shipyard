"""Run the solver on instances with OGC_STAGE_TIMING=1 and aggregate the two
stderr instrumentation lines into ONE per-instance / per-stage record:

  [STAGE_TIMING]{...}  -> wall-seconds per pipeline stage
  [STAGE_OBJ]{...}     -> objective reduction (delta) + adoption count per stage,
                          plus the postprocess base (search incumbent) objective.

The join of the two answers the two operative questions:
  * GOAL 1 (which lever matters): stages with large `delta`.
  * GOAL 2 (wasted time): stages with time>0 but delta==0 (ran, never improved).

Each (instance, solver) runs in an isolated process via tools/run_solver_once.py
(same isolation the eval server uses).  Output: a JSON record set + a console
table.  Read-only w.r.t. the solver.

Usage (from project root, conda env ogc2025):
  python tools/collect_trace.py --timelimit 300 --conc 4
  python tools/collect_trace.py --timelimit 120 --instances prob_11,prob_13,prob_20
  python tools/collect_trace.py --timelimit 300 --conc 4 --out results/trace_agg.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAIN = ROOT / "instances" / "train"

_TIMING_RE = re.compile(r"^\[STAGE_TIMING\](\{.*\})\s*$")
_OBJ_RE = re.compile(r"^\[STAGE_OBJ\](\{.*\})\s*$")

# Stages that belong to the search phase (pre-postprocess) vs postprocess levers.
SEARCH_STAGES = {"baseline", "search", "seeds_decode", "cpsat_seed"}


def _instances(spec: str | None) -> list[str]:
    if spec:
        names = [s.strip() for s in spec.split(",") if s.strip()]
    else:
        names = sorted((p.stem for p in TRAIN.glob("prob_*.json")),
                       key=lambda s: int(s.split("_")[-1]))
    return names


def run_one(name: str, timelimit: float) -> dict:
    """Run one instance with stage instrumentation; parse both lines."""
    inst = TRAIN / f"{name}.json"
    sol_out = ROOT / "results" / f"_trace_{name}.json"
    env = dict(os.environ)
    env["OGC_STAGE_TIMING"] = "1"
    cmd = [sys.executable, str(ROOT / "tools" / "run_solver_once.py"),
           str(inst), "--solver", "our", "--timelimit", str(timelimit),
           "--save-sol", str(sol_out)]
    rec: dict = {"instance": name, "ok": False}
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                           text=True, timeout=timelimit + 600)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec
    # The run result JSON is the last stdout line.
    for line in reversed(p.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                r = json.loads(line)
                rec.update({"feasible": r.get("feasible"),
                            "obj1": r.get("obj1"), "obj2": r.get("obj2"),
                            "obj3": r.get("obj3"),
                            "objective": r.get("objective"),
                            "elapsed": r.get("elapsed")})
                break
            except Exception:
                continue
    timing = obj = None
    for line in p.stderr.splitlines():
        m = _TIMING_RE.match(line.strip())
        if m:
            timing = json.loads(m.group(1))
        m = _OBJ_RE.match(line.strip())
        if m:
            obj = json.loads(m.group(1))
    if timing is None:
        rec["error"] = "no STAGE_TIMING line"
        return rec
    rec["ok"] = True
    rec["total_s"] = timing.get("total_s")
    rec["n_blocks"] = timing.get("n_blocks")
    rec["n_bays"] = timing.get("n_bays")
    times = timing.get("stages", {}) or {}
    deltas = (obj or {}).get("stages", {}) or {}
    base = deltas.get("_postproc_base", {})
    rec["postproc_base_obj"] = base.get("obj")
    rec["final_obj_traced"] = (obj or {}).get("final_obj")
    # join per stage
    names = set(times) | {k for k in deltas if k != "_postproc_base"}
    stages = {}
    for sname in names:
        t = float(times.get(sname, 0.0) or 0.0)
        d = deltas.get(sname, {})
        stages[sname] = {
            "time_s": round(t, 3),
            "delta": d.get("delta", 0.0),
            "n_adopt": d.get("n_adopt", 0),
            "phase": "search" if sname in SEARCH_STAGES else "postproc",
        }
    rec["stages"] = stages
    rec["other_s"] = timing.get("search_baseline_other_s")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timelimit", type=float, default=300.0)
    ap.add_argument("--instances", default=None,
                    help="comma list e.g. prob_11,prob_13")
    ap.add_argument("--conc", type=int, default=1)
    ap.add_argument("--out", default="results/trace_agg.json")
    args = ap.parse_args()

    names = _instances(args.instances)
    print(f"[collect_trace] {len(names)} instances @ {args.timelimit}s "
          f"conc={args.conc}", file=sys.stderr, flush=True)

    recs: dict[str, dict] = {}
    if args.conc > 1:
        with cf.ThreadPoolExecutor(max_workers=args.conc) as ex:
            futs = {ex.submit(run_one, n, args.timelimit): n for n in names}
            for fut in cf.as_completed(futs):
                r = fut.result()
                recs[r["instance"]] = r
                print(f"  done {r['instance']:9} "
                      f"Z1={r.get('obj1')} feas={r.get('feasible')}",
                      file=sys.stderr, flush=True)
    else:
        for n in names:
            r = run_one(n, args.timelimit)
            recs[r["instance"]] = r
            print(f"  done {n:9} Z1={r.get('obj1')} feas={r.get('feasible')}",
                  file=sys.stderr, flush=True)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    ordered = {n: recs[n] for n in names if n in recs}
    out.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

    # ---- console summary -------------------------------------------------- #
    print()
    print(f"{'inst':9} {'Z1':>4} {'total_s':>8} {'srch_s':>7} {'post_s':>7} "
          f"{'top_lever(delta,t)':>40}")
    print("-" * 92)
    waste_rows = []
    for n in names:
        r = recs.get(n, {})
        if not r.get("ok"):
            print(f"{n:9} {'ERR':>4} {r.get('error','?')[:60]}")
            continue
        stages = r["stages"]
        srch = sum(s["time_s"] for s in stages.values() if s["phase"] == "search")
        post = sum(s["time_s"] for s in stages.values() if s["phase"] == "postproc")
        # top postproc lever by delta
        post_levers = [(k, v) for k, v in stages.items() if v["phase"] == "postproc"]
        post_levers.sort(key=lambda kv: -kv[1]["delta"])
        top = post_levers[0] if post_levers else None
        topstr = (f"{top[0]}(d={top[1]['delta']:.0f},t={top[1]['time_s']:.0f}s)"
                  if top and top[1]["delta"] > 0 else "-")
        print(f"{n:9} {str(r.get('obj1')):>4} {r.get('total_s',0):>8.1f} "
              f"{srch:>7.1f} {post:>7.1f} {topstr:>40}")
        # wasted stages: time>1s but delta==0
        for k, v in stages.items():
            if v["time_s"] > 1.0 and v["delta"] == 0.0 and v["phase"] == "postproc":
                waste_rows.append((n, k, v["time_s"]))

    if waste_rows:
        print("\n[WASTED postproc time: ran >1s, ZERO objective gain]")
        waste_rows.sort(key=lambda x: -x[2])
        for (n, k, t) in waste_rows[:30]:
            print(f"  {n:9} {k:22} {t:6.1f}s")
        print(f"  total wasted: {sum(w[2] for w in waste_rows):.1f}s "
              f"across {len(waste_rows)} (instance,stage) pairs")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
