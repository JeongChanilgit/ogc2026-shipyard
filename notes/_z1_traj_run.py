"""Z1-trajectory measurement harness (BOUNDED CONCURRENCY) — "solve ALL 20" mode.

Runs the OGC2026 solver on every train instance prob_1..prob_20, in prob_1..prob_20
numeric submission order, with up to --concurrency solver processes in flight at
once (default 4), each instance configured to STOP the moment z1 hits 0
(OGC_CPSAT_ZERO_STOP + OGC_EXIT_ON_Z1_ZERO).  Each run produces a DENSE
1-second-resolution z1 curve reconstructed from the solver's [Z1_TRACE] stderr
line, plus the LABELED stage marks from [STAGE_TIMING]/[STAGE_OBJ].  The FINAL z1
is scored authoritatively via tools/ogc_analysis.obj_tuple (official check).

Real-time: each run streams its z1 changes to OGC_Z1_LIVE_FILE (a JSONL file the
solver flushes mid-run) so an external watcher (notes/_z1_traj_watch.py) can
render the in-progress curve live.  The watcher (NOT this runner) regenerates the
20-panel HTML every ~3 s; this runner regenerates it ONCE at the very end (so the
report is fully up to date after exit) — it must NOT call the plotter mid-loop,
because several concurrent threads invoking the plotter would race and corrupt the
PNG.  A results/z1traj/_STATUS.json lists in-flight + completed instances and a
results/z1traj/_DONE sentinel is written at the very end so the watcher can stop.

Why BOUNDED CONCURRENCY (and why it's safe): the eval server gives each instance a
4-core budget, and each of our solves peaks at ~4 cores (CP-SAT num_search_workers
= 4 / parallel cum_level MAX_WORKERS = 4).  On this 20-core box, running up to 4
solves at once = 4 x 4 = 16 cores <= 20, so there is NO oversubscription: each
solver still gets its full per-instance 4-core budget exactly as on the eval
server, so timing/objective measurements are NOT distorted by CPU contention (the
old ±20x non-determinism artifact came from oversubscription, which 4x4<=20
avoids).  We use a ThreadPoolExecutor: run_one() blocks in subprocess.run, which
releases the GIL while waiting on the child, so threads give real parallelism here
and each task keeps its OWN per-(inst,config) live/sol/result paths (no collision).

Why a fresh subprocess per config: the solver reads its OGC_* env flags at
IMPORT time, so a config switch REQUIRES a new interpreter.  We reuse
tools/run_solver_once.py (isolated process; emits the result JSON on stdout and
[Z1_TRACE]/[STAGE_TIMING]/[STAGE_OBJ] on stderr) plus --save-sol so we can
re-score the produced solution.

Usage (from project root):
  conda run -n ogc2025 python notes/_z1_traj_run.py --timelimit 300
  conda run -n ogc2025 python notes/_z1_traj_run.py --instances prob_11 --timelimit 25 --configs solve
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAIN = ROOT / "instances" / "train"
OUT_DIR = ROOT / "results" / "z1traj"

sys.path.insert(0, str(ROOT / "tools"))
import ogc_analysis  # noqa: E402  (load_instance + obj_tuple, official scoring)

# ---- defaults (overridable via argv) ------------------------------------- #
# Numeric order 1..20 (NOT lexicographic) — solve from #1.
DEFAULT_INSTANCES = [f"prob_{n}" for n in range(1, 21)]
DEFAULT_TIMELIMIT = 300.0

# Subprocess interpreter: make the harness self-contained regardless of which
# interpreter launches it.  We prefer the conda form for robustness.
# Call the env's python DIRECTLY (NOT `conda run`): `conda run` is not
# concurrency-safe — several simultaneous invocations race on its temp activation
# scripts and crash the child at startup (~1.8s, "no solution file").  The env's
# python.exe resolves its own site-packages + DLLs without activation, so direct
# invocation is both correct and concurrency-safe.
CONDA_PREFIX = [r"C:\Users\peter\anaconda3\envs\ogc2025\python.exe"]

# "solve" is the default = BEST algorithm: parallel cum_level (4 cores) + fast
# redecode + CP-SAT zero-stop + stop-at-z1=0 + tracing.  NOTE: with cum_level
# PARALLEL on, its internal per-bay marks run in worker subprocesses and are NOT
# streamed, so the cum_level part of the curve is coarse (one adoption point);
# other stages stay densely traced.  "baseline" (tracing only, sequential, no
# early stop) is selectable for the detailed cum_level curve but is not default.
CONFIGS: dict[str, dict[str, str]] = {
    "solve": {
        "OGC_CUMLEVEL_PARALLEL": "1",
        "OGC_REDECODE_FAST": "1",
        "OGC_CPSAT_ZERO_STOP": "1",
        "OGC_EXIT_ON_Z1_ZERO": "1",
        "OGC_Z1_TRACE": "1",
        "OGC_STAGE_TIMING": "1",
    },
    "baseline": {
        "OGC_Z1_TRACE": "1",
        "OGC_STAGE_TIMING": "1",
    },
    # A/B experiment: identical to "solve" but skips the greedy baseline entirely
    # (trivial floor + search/seed path + gate-postprocess only).  Answers: can we
    # reach Z1=0 / stay feasible WITHOUT the greedy baseline?
    "nobaseline": {
        "OGC_CUMLEVEL_PARALLEL": "1",
        "OGC_REDECODE_FAST": "1",
        "OGC_CPSAT_ZERO_STOP": "1",
        "OGC_EXIT_ON_Z1_ZERO": "1",
        "OGC_Z1_TRACE": "1",
        "OGC_STAGE_TIMING": "1",
        "OGC_SKIP_BASELINE": "1",
    },
}
DEFAULT_CONFIGS = ["solve"]

_TIMING_RE = re.compile(r"^\[STAGE_TIMING\](\{.*\})\s*$")
_OBJ_RE = re.compile(r"^\[STAGE_OBJ\](\{.*\})\s*$")
_TRACE_RE = re.compile(r"^\[Z1_TRACE\](\{.*\})\s*$")


def _parse_stage_lines(stderr: str):
    """Return (timing_dict, obj_dict, trace_changes) parsed from the three
    instrumentation lines; missing ones come back as None / []."""
    timing = obj = None
    changes: list = []
    for line in stderr.splitlines():
        line = line.strip()
        m = _TIMING_RE.match(line)
        if m:
            timing = json.loads(m.group(1))
            continue
        m = _OBJ_RE.match(line)
        if m:
            obj = json.loads(m.group(1))
            continue
        m = _TRACE_RE.match(line)
        if m:
            try:
                changes = json.loads(m.group(1)).get("changes", []) or []
            except Exception:
                changes = []
    return timing, obj, changes


def _dense_1hz(changes: list, wall_total: float | None = None) -> list:
    """Reconstruct a DENSE 1-second-resolution step trajectory from the solver's
    [Z1_TRACE] change points, CARRYING THE STAGE that produced each value.

    changes = [[t, z1, stage], ...] in chronological order (t = seconds since
    algorithm start, recorded at EVERY z1 change; stage = name of the solver
    stage that emitted the change).  Legacy 2-element [t, z1] points are tolerated
    (stage defaults to "").  We return the sorted union of:
      * every original change point [t, z1, stage], and
      * one point at each integer second `s` (0..ceil(wall_total)) carrying the
        value AND STAGE of the LAST change at-or-before `s` (zero-order-hold),
    extended out to `wall_total` so the final plateau is visible.

    The result is suitable for drawstyle="steps-post".  Empty input -> [].
    """
    pts: list[list] = []
    for c in changes:
        if c is None or len(c) < 2:
            continue
        t, z = c[0], c[1]
        stage = str(c[2]) if len(c) >= 3 and c[2] is not None else ""
        if t is None or z is None:
            continue
        pts.append([float(t), float(z), stage])
    if not pts:
        return []
    pts.sort(key=lambda p: p[0])
    t_last = pts[-1][0]
    wall = float(wall_total) if wall_total else t_last
    wall = max(wall, t_last)

    out: list[list] = []
    seen_t: set = set()

    def _push(t: float, z: float, stage: str) -> None:
        key = round(t, 3)
        if key in seen_t:
            return
        seen_t.add(key)
        out.append([key, float(z), str(stage)])

    # zero-order-hold sampler over the sorted change points.
    idx = 0
    sec = 0
    last_sec = int(math.ceil(wall))
    # first emit every change point (with its own stage), then every integer sec.
    for t, z, stage in pts:
        _push(t, z, stage)
    while sec <= last_sec:
        # advance the held value/stage to the last change at-or-before `sec`.
        while idx + 1 < len(pts) and pts[idx + 1][0] <= sec:
            idx += 1
        cur_z = pts[idx][1]
        cur_stage = pts[idx][2]
        # only emit seconds within the traced span (don't fabricate before first t).
        if sec >= pts[0][0] - 1e-9:
            _push(float(sec), cur_z, cur_stage)
        sec += 1
    # ensure a trailing plateau point at exactly wall_total (held value+stage).
    if wall > t_last:
        _push(round(wall, 3), pts[-1][1], pts[-1][2])
    out.sort(key=lambda p: p[0])
    return out


def _build_stage_marks(timing: dict | None, obj: dict | None, final_z1=None):
    """Build the LABELED stage trajectory [[t_cum, z1, label], ...].

    (Same mechanics as the previous _build_trajectory, kept for the stage-mark
    overlay.)  Drives the clock off [STAGE_OBJ]'s chronological stage order and
    looks up each stage's duration in [STAGE_TIMING].
    """
    durations = (timing.get("stages", {}) if timing else {}) or {}
    stages = (obj.get("stages", {}) if obj else {}) or {}

    search_stages = {"baseline", "search", "seeds_decode", "cpsat_seed"}
    search_t = sum(float(durations.get(s, 0.0) or 0.0) for s in search_stages)

    traj: list[list] = []

    base = stages.get("_postproc_base") if isinstance(stages, dict) else None
    start_z1 = base.get("obj1") if isinstance(base, dict) else None
    if start_z1 is not None:
        traj.append([round(search_t, 3), float(start_z1), "incumbent"])

    t_cum = search_t
    for sname, sdata in stages.items():
        if sname == "_postproc_base":
            continue
        if not isinstance(sdata, dict):
            continue
        t_cum += float(durations.get(sname, 0.0) or 0.0)
        z1 = sdata.get("z1")
        if z1 is None:
            continue
        traj.append([round(t_cum, 3), float(z1), str(sname)])

    if final_z1 is not None:
        total_s = float(timing.get("total_s", t_cum)) if timing else t_cum
        tail_t = round(max(total_s, t_cum), 3)
        if not traj:
            traj.append([tail_t, float(final_z1), "final"])
        elif abs(traj[-1][1] - float(final_z1)) > 1e-6 or tail_t > traj[-1][0]:
            traj.append([tail_t, float(final_z1), "final"])
    return traj


def run_one(inst: str, config: str, timelimit: float) -> dict:
    """Run ONE (instance, config) in an isolated subprocess; parse stage/trace
    lines; score the produced solution with the official check.  Never raises."""
    inst_path = TRAIN / f"{inst}.json"
    sol_out = OUT_DIR / f"_sol_{inst}_{config}.json"
    live_path = OUT_DIR / f"_live_{inst}_{config}.jsonl"
    # TRUNCATE/delete the live file BEFORE launch so the watcher never reads a
    # stale curve from a previous run of the same instance.
    try:
        live_path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass

    env = dict(os.environ)
    for k, v in CONFIGS[config].items():
        env[k] = v
    env["OGC_Z1_LIVE_FILE"] = str(live_path)

    cmd = CONDA_PREFIX + [
        str(ROOT / "tools" / "run_solver_once.py"),
        str(inst_path), "--solver", "our",
        "--timelimit", str(timelimit),
        "--save-sol", str(sol_out),
    ]

    rec: dict = {
        "instance": inst, "config": config, "timelimit": timelimit,
        "dense": [], "stage_marks": [], "final_z1": None, "final_obj": None,
        "feasible": False, "wall_total": None,
        "reached_zero": False, "early_exit": False,
    }
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                           text=True, timeout=timelimit + 600)
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["wall_total"] = round(time.perf_counter() - t0, 2)
        return rec
    rec["wall_total"] = round(time.perf_counter() - t0, 2)

    timing, obj, changes = _parse_stage_lines(p.stderr)

    # Authoritative final score via the official check on the saved solution.
    if sol_out.exists():
        try:
            prob = ogc_analysis.load_instance(str(inst_path))
            sol = ogc_analysis.load_solution(str(sol_out))
            feasible, objective, z1, _z2, _z3 = ogc_analysis.obj_tuple(prob, sol)
            rec["feasible"] = bool(feasible)
            rec["final_obj"] = objective
            rec["final_z1"] = z1
        except Exception as e:
            rec["error"] = f"score: {type(e).__name__}: {e}"
    else:
        rec["error"] = "no solution file"
        for line in reversed(p.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    r = json.loads(line)
                    if r.get("error"):
                        rec["error"] = r["error"]
                except Exception:
                    pass
                break

    rec["dense"] = _dense_1hz(changes, rec.get("wall_total"))
    rec["stage_marks"] = _build_stage_marks(timing, obj, rec.get("final_z1"))

    fz = rec.get("final_z1")
    rec["reached_zero"] = bool(fz is not None and fz <= 1e-9)
    rec["early_exit"] = bool(rec["reached_zero"]
                             and rec["wall_total"] is not None
                             and rec["wall_total"] < timelimit - 5)
    return rec


PLOT = ROOT / "notes" / "_z1_traj_plot.py"
STATUS = OUT_DIR / "_STATUS.json"
DONE = OUT_DIR / "_DONE"


def _regen_html() -> None:
    """Regenerate the 20-panel PNG+HTML from whatever per-run JSON exists so far
    (called after EVERY run -> the report grows one instance at a time)."""
    try:
        subprocess.run([sys.executable, str(PLOT)], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=180)
    except Exception:
        pass


def _write_status(running, done_list) -> None:
    """Write _STATUS.json: running = LIST of in-flight instance names, done =
    LIST of completed instance names.  Caller MUST hold the status lock."""
    try:
        STATUS.write_text(json.dumps(
            {"running": list(running), "done": list(done_list),
             "ts": int(time.time())}),
            encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timelimit", type=float, default=DEFAULT_TIMELIMIT)
    ap.add_argument("--instances", default=",".join(DEFAULT_INSTANCES),
                    help="comma list e.g. prob_15 or prob_1,prob_2")
    ap.add_argument("--configs", default=",".join(DEFAULT_CONFIGS),
                    help="comma list of: " + ",".join(CONFIGS.keys()))
    ap.add_argument("--concurrency", type=int, default=4,
                    help="max solver processes in flight at once "
                         "(default 4 -> 4x4=16 cores <= 20, no oversubscription)")
    args = ap.parse_args()

    instances = [s.strip() for s in args.instances.split(",") if s.strip()]
    configs = [s.strip() for s in args.configs.split(",") if s.strip()]
    bad = [c for c in configs if c not in CONFIGS]
    if bad:
        print(f"[error] unknown config(s): {bad}; known={list(CONFIGS)}")
        return 2
    concurrency = max(1, int(args.concurrency))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # fresh DONE sentinel state for this campaign.
    try:
        DONE.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass

    print(f"[z1_traj] {len(instances)} inst x {len(configs)} cfg @ "
          f"{args.timelimit}s concurrency={concurrency} (solve-all)",
          file=sys.stderr, flush=True)

    # All (instance, config) tasks in prob_1..prob_20 numeric submission order
    # (instances arg already arrives in that order; configs preserve their order).
    tasks = [(inst, config) for inst in instances for config in configs]

    # Shared mutable state guarded by a SINGLE lock: the in-flight instance set,
    # the completed-instance list, _STATUS.json writes, and progress prints.
    lock = threading.Lock()
    running: set[str] = set()
    done: list[str] = []

    def _task(inst: str, config: str):
        """Mark inst running (under lock), run the solver, then write the per-run
        JSON, update _STATUS, and print progress (under lock).  Returns nothing —
        all side effects are the JSON file + shared status."""
        with lock:
            running.add(inst)
            _write_status(running, done)
        rec = run_one(inst, config, args.timelimit)
        out = OUT_DIR / f"{inst}_{config}.json"
        out.write_text(json.dumps(rec, indent=2, default=str), encoding="utf-8")
        with lock:
            running.discard(inst)
            if inst not in done:
                done.append(inst)
            _write_status(running, done)
            z1 = rec["final_z1"]
            print(f"{inst} {config}: z1={z1} reached0={rec['reached_zero']} "
                  f"wall={rec['wall_total']}s (early_exit={rec['early_exit']})"
                  + (f" ERR={rec['error']}" if rec.get("error") else ""),
                  flush=True)

    with lock:
        _write_status(running, done)  # publish empty status before launch
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(_task, inst, config) for inst, config in tasks]
        for fut in as_completed(futures):
            # surface any unexpected exception (run_one itself never raises, but
            # the JSON write / status update could).
            exc = fut.exception()
            if exc is not None:
                with lock:
                    print(f"[z1_traj] task error: "
                          f"{type(exc).__name__}: {exc}", flush=True)

    # sentinel: tell the watcher we're finished.
    try:
        DONE.write_text(json.dumps({"ts": int(time.time()), "done": done}),
                        encoding="utf-8")
    except Exception:
        pass
    # Regenerate the report ONCE, after ALL futures complete (never mid-loop:
    # concurrent plotter invocations would race and corrupt the PNG).
    _regen_html()
    print(f"[z1_traj] wrote per-run JSON to {OUT_DIR}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
