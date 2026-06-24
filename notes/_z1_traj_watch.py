"""Real-time watcher for the Z1-trajectory "solve-all" harness.

Polls results/z1traj/ every ~3 s and re-renders the 20-panel HTML so the report
updates LIVE while notes/_z1_traj_run.py solves prob_1..prob_20 in order.  For
each instance it prefers a completed per-run JSON (live=False); otherwise, if a
_live_<inst>_solve.jsonl exists and is non-empty, it reads those streamed points
and reconstructs the in-progress curve with the SAME _dense_1hz the runner uses.

Stops when results/z1traj/_DONE appears (one final render, then exit) or after a
max wall of ~2 hours.  Never crashes on a half-written / locked file.

Usage (from project root, run in the BACKGROUND before the runner):
  conda run -n ogc2025 python notes/_z1_traj_watch.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "results" / "z1traj"
DONE = OUT_DIR / "_DONE"

# DRY: reuse the runner's dense-resampler and the plotter's renderer.
sys.path.insert(0, str(ROOT / "notes"))
import _z1_traj_run as run  # noqa: E402  (for _dense_1hz)
import _z1_traj_plot as plot  # noqa: E402  (for render + INSTANCES)

INSTANCES = plot.INSTANCES
TICK_SECONDS = 3.0
MAX_WALL_SECONDS = 2 * 60 * 60  # ~2 hours


def _read_completed(inst: str) -> dict | None:
    """Return a render dict from a completed per-run JSON, or None."""
    for cfg in ("solve", "baseline"):  # solve wins.
        f = OUT_DIR / f"{inst}_{cfg}.json"
        if not f.exists():
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        return {
            "dense": r.get("dense") or [],
            "stage_marks": r.get("stage_marks") or [],
            "final_z1": r.get("final_z1"),
            "feasible": r.get("feasible"),
            "wall": r.get("wall_total"),
            "live": False,
            "reached_zero": bool(r.get("reached_zero")),
            "early_exit": bool(r.get("early_exit")),
        }
    return None


def _read_live(inst: str) -> dict | None:
    """Return a LIVE render dict from the in-progress JSONL stream, or None."""
    live = OUT_DIR / f"_live_{inst}_solve.jsonl"
    if not live.exists():
        return None
    try:
        text = live.read_text(encoding="utf-8")
    except Exception:
        return None
    changes: list = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
            t, z = o.get("t"), o.get("z1")
            stage = o.get("stage")  # optional; "" if absent
            if t is not None and z is not None:
                changes.append([float(t), float(z),
                                str(stage) if stage is not None else ""])
        except Exception:
            continue  # skip half-written trailing line
    if not changes:
        return None
    wall = changes[-1][0]
    dense = run._dense_1hz(changes, wall)
    last_z = changes[-1][1]
    cur_stage = changes[-1][2]  # CURRENT stage = stage of the LAST live point.
    return {
        "dense": dense,
        "stage_marks": [],          # stage marks land only at run end.
        "final_z1": None,
        "feasible": None,
        "wall": wall,
        "live": True,
        "cur_stage": cur_stage,
        "reached_zero": bool(last_z <= 1e-9),
        "early_exit": False,
    }


def _build_data() -> tuple[dict, int, str | None, int]:
    """Return (data, n_done, live_inst, n_zeros) for one tick."""
    data: dict = {}
    n_done = 0
    n_zeros = 0
    live_inst = None
    for inst in INSTANCES:
        d = None
        try:
            d = _read_completed(inst)
            if d is not None:
                n_done += 1
            else:
                d = _read_live(inst)
                if d is not None:
                    live_inst = inst
        except Exception:
            d = None
        if d is None:
            continue
        if d.get("reached_zero"):
            n_zeros += 1
        data[inst] = d
    return data, n_done, live_inst, n_zeros


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    print(f"[watch] started; polling {OUT_DIR} every {TICK_SECONDS}s "
          f"(stop on {DONE.name} or {MAX_WALL_SECONDS}s)", flush=True)

    while True:
        finished = DONE.exists()
        try:
            data, n_done, live_inst, n_zeros = _build_data()
            plot.render(data)
        except Exception as e:
            print(f"[watch] render error (continuing): "
                  f"{type(e).__name__}: {e}", flush=True)
            n_done = live_inst = n_zeros = None
        print(f"[watch] done={n_done} live={live_inst} zeros={n_zeros}",
              flush=True)

        if finished:
            print("[watch] _DONE seen -> final render done, exiting.", flush=True)
            return 0
        if time.time() - t_start > MAX_WALL_SECONDS:
            print("[watch] max wall reached -> exiting.", flush=True)
            return 0
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
