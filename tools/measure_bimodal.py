"""Sequential bimodality probe for prob_13/prob_14/prob_15.

Runs each target instance in a fresh Python process, one at a time, with
OGC_BIMODAL_LOG armed.  The solver logic is unchanged; the probe only collects
JSONL events emitted by src/instrument.py, src/baseline_greedy.py, and
src/myalgorithm.py.

Example:
    python tools/measure_bimodal.py --runs 20 --timelimit 60
    python tools/measure_bimodal.py instances/train/prob_14.json --runs 5
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DEFAULT_INSTANCES = [
    ROOT / "instances" / "train" / "prob_13.json",
    ROOT / "instances" / "train" / "prob_14.json",
    ROOT / "instances" / "train" / "prob_15.json",
]


def _json_dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _child(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(SRC))
    os.environ["OGC_BIMODAL_LOG"] = str(args.events)
    os.environ["OGC_BIMODAL_RUN_ID"] = args.run_id

    summary = {
        "run_id": args.run_id,
        "instance_path": str(args.instance),
        "instance": Path(args.instance).stem,
        "timelimit": args.timelimit,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "elapsed": None,
        "feasible": False,
        "stage": None,
        "objective": None,
        "obj1": None,
        "obj2": None,
        "obj3": None,
        "error": None,
    }
    try:
        with Path(args.instance).open(encoding="utf-8") as f:
            prob_info = json.load(f)
        summary["problem_name"] = prob_info.get("name")

        from myalgorithm import algorithm
        from utils import check_feasibility
        from instrument import bimodal_log, bimodal_flush

        t0 = time.perf_counter()
        sol = algorithm(prob_info, args.timelimit)
        summary["elapsed"] = time.perf_counter() - t0
        rep = check_feasibility(prob_info, sol)
        summary.update({
            "feasible": bool(rep.get("feasible")),
            "stage": rep.get("stage"),
            "objective": rep.get("objective"),
            "obj1": rep.get("obj1"),
            "obj2": rep.get("obj2"),
            "obj3": rep.get("obj3"),
        })
        bimodal_log("run_result", **summary)
        bimodal_flush()
    except Exception:
        summary["error"] = traceback.format_exc()
        try:
            from instrument import bimodal_log, bimodal_flush
            bimodal_log("run_result", **summary)
            bimodal_flush()
        except Exception:
            pass
    finally:
        _json_dump(Path(args.summary), summary)

    return 0 if summary["error"] is None else 1


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _run_events(events_by_run: dict[str, list[dict]], run_id: str, kind: str) -> list[dict]:
    return [e for e in events_by_run.get(run_id, []) if e.get("kind") == kind]


def _forced_blocks(events_by_run: dict[str, list[dict]], run_id: str) -> tuple[int, ...]:
    blocks = set()
    for e in events_by_run.get(run_id, []):
        if e.get("kind") in ("baseline_force_place", "baseline_force_mark"):
            bid = e.get("block_id")
            if bid is not None:
                blocks.add(int(bid))
    return tuple(sorted(blocks))


def _phase1_z1(events_by_run: dict[str, list[dict]], run_id: str):
    evs = _run_events(events_by_run, run_id, "baseline_phase1_done")
    return evs[-1].get("z1") if evs else None


def _natural_progress(events_by_run: dict[str, list[dict]], run_id: str):
    evs = _run_events(events_by_run, run_id, "baseline_repair_done")
    if evs:
        return evs[-1].get("progress_ratio")
    evs = _run_events(events_by_run, run_id, "baseline_phase1_done")
    return evs[-1].get("progress_ratio") if evs else None


def _placement_sequence(events_by_run: dict[str, list[dict]], run_id: str):
    seq = []
    for e in _run_events(events_by_run, run_id, "baseline_placement"):
        seq.append((
            e.get("phase"),
            e.get("block_id"),
            e.get("bay_id"),
            e.get("x"),
            e.get("y"),
            e.get("orient_idx"),
            bool(e.get("forced")),
        ))
    return seq


def _first_force_index(seq) -> int | None:
    for i, item in enumerate(seq):
        if item[-1]:
            return i
    return None


def _divergence_bit(run_ids: list[str], events_by_run: dict[str, list[dict]]) -> dict:
    seqs = {rid: _placement_sequence(events_by_run, rid) for rid in run_ids}
    ref_id = next((rid for rid in run_ids if seqs.get(rid)), None)
    if ref_id is None:
        return {"bit": "insufficient", "comparisons": []}

    ref = seqs[ref_id]
    ref_force = _first_force_index(ref)
    comparisons = []
    labels = []
    for rid in run_ids:
        if rid == ref_id or not seqs.get(rid):
            continue
        cur = seqs[rid]
        div = None
        for i, (a, b) in enumerate(zip(ref, cur)):
            if a != b:
                div = i
                break
        if div is None and len(ref) != len(cur):
            div = min(len(ref), len(cur))
        cur_force = _first_force_index(cur)
        force_candidates = [x for x in (ref_force, cur_force) if x is not None]
        first_force = min(force_candidates) if force_candidates else None
        if div is None:
            label = "same"
        elif first_force is not None and div >= max(0, first_force - 1):
            label = "force_place_boundary"
        else:
            label = "normal_region"
        labels.append(label)
        comparisons.append({
            "run_id": rid,
            "first_divergence_index": div,
            "first_force_index": first_force,
            "label": label,
        })

    if any(x == "normal_region" for x in labels):
        bit = "normal_region"
    elif any(x == "force_place_boundary" for x in labels):
        bit = "force_place_boundary"
    elif labels:
        bit = "same_no_divergence"
    else:
        bit = "insufficient"
    return {"reference_run_id": ref_id, "bit": bit, "comparisons": comparisons}


def _summarize_instance(instance: str, rows: list[dict],
                        events_by_run: dict[str, list[dict]]) -> dict:
    valid = [r for r in rows if r.get("objective") is not None]
    objectives = [float(r["objective"]) for r in valid]
    median_obj = statistics.median(objectives) if objectives else None
    threshold = (median_obj * 3.0) if median_obj is not None else None
    explosion = [
        r for r in valid
        if threshold is not None and float(r["objective"]) >= threshold
    ]
    run_ids = [r["run_id"] for r in rows]
    forced = {rid: _forced_blocks(events_by_run, rid) for rid in run_ids}
    forced_counts = {rid: len(forced[rid]) for rid in run_ids}

    if len(explosion) >= 2:
        sets = [forced[r["run_id"]] for r in explosion]
        bit1 = "same" if all(s == sets[0] for s in sets[1:]) else "different"
    elif len(explosion) == 1:
        bit1 = "single_explosion"
    else:
        bit1 = "no_explosion"

    zero_rows = [r for r in valid if forced_counts.get(r["run_id"], 0) == 0]
    zero_z1 = [
        float(r["obj1"]) for r in zero_rows
        if r.get("obj1") is not None
    ]
    if len(zero_z1) < 2:
        bit2 = "insufficient"
        zero_z1_ratio = None
    else:
        lo, hi = min(zero_z1), max(zero_z1)
        zero_z1_ratio = 1.0 if hi == 0 else (float("inf") if lo == 0 else hi / lo)
        if zero_z1_ratio <= 1.5:
            bit2 = "13pct_axis"
        elif zero_z1_ratio >= 3.0:
            bit2 = "18x_axis"
        else:
            bit2 = "middle"

    progress_vals = [
        p for p in (_natural_progress(events_by_run, r["run_id"]) for r in zero_rows)
        if isinstance(p, (int, float))
    ]
    if len(progress_vals) < 2:
        bit3 = "insufficient"
        progress_band = None
    else:
        progress_band = max(progress_vals) - min(progress_vals)
        bit3 = "narrow" if progress_band <= 0.05 else "wide"

    div = _divergence_bit(run_ids, events_by_run)

    table = []
    for r in rows:
        rid = r["run_id"]
        table.append({
            "run_id": rid,
            "objective": r.get("objective"),
            "obj1": r.get("obj1"),
            "elapsed": r.get("elapsed"),
            "feasible": r.get("feasible"),
            "forced_count": forced_counts.get(rid, 0),
            "forced_set": list(forced.get(rid, ())),
            "phase1_z1": _phase1_z1(events_by_run, rid),
            "natural_progress": _natural_progress(events_by_run, rid),
            "pythonhashseed": r.get("pythonhashseed"),
            "error": r.get("error"),
        })

    return {
        "instance": instance,
        "runs": len(rows),
        "valid_runs": len(valid),
        "objective_min": min(objectives) if objectives else None,
        "objective_median": median_obj,
        "objective_max": max(objectives) if objectives else None,
        "explosion_threshold": threshold,
        "explosion_run_ids": [r["run_id"] for r in explosion],
        "bits": {
            "forced_set_explosion_same_or_different": bit1,
            "forced_zero_z1_axis": bit2,
            "natural_progress_band": bit3,
            "first_sequence_divergence": div.get("bit"),
        },
        "diagnostics": {
            "forced_zero_z1_ratio": zero_z1_ratio,
            "natural_progress_band_width": progress_band,
            "sequence_divergence": div,
        },
        "run_table": table,
    }


def _render_md(summary: dict) -> str:
    lines = ["# Bimodal Measurement Summary", ""]
    lines.append(f"- generated_at: {summary['generated_at']}")
    lines.append(f"- runs_per_instance: {summary['runs_per_instance']}")
    lines.append(f"- timelimit: {summary['timelimit']}")
    lines.append("")
    for inst in summary["instances"]:
        b = inst["bits"]
        lines.append(f"## {inst['instance']}")
        lines.append(
            f"- objective min/median/max: {inst['objective_min']} / "
            f"{inst['objective_median']} / {inst['objective_max']}"
        )
        lines.append(f"- explosion runs: {inst['explosion_run_ids']}")
        lines.append(f"- bit1 forced-set on explosions: {b['forced_set_explosion_same_or_different']}")
        lines.append(f"- bit2 forced=0 Z1 axis: {b['forced_zero_z1_axis']}")
        lines.append(f"- bit3 natural progress band: {b['natural_progress_band']}")
        lines.append(f"- bit4 first sequence divergence: {b['first_sequence_divergence']}")
        lines.append("")
        lines.append("| run | feasible | objective | Z1 | forced | elapsed |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for r in inst["run_table"]:
            lines.append(
                f"| {r['run_id']} | {r['feasible']} | {r['objective']} | "
                f"{r['obj1']} | {r['forced_count']} | {r['elapsed']} |"
            )
        lines.append("")
    return "\n".join(lines)


def _parent(args: argparse.Namespace) -> int:
    instances = [Path(p) for p in (args.instances or DEFAULT_INSTANCES)]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else ROOT / "results" / f"bimodal_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.jsonl"
    summaries = []

    for inst in instances:
        if not inst.exists():
            raise FileNotFoundError(inst)
        for idx in range(args.runs):
            run_id = f"{inst.stem}_r{idx + 1:02d}"
            child_summary = out_dir / f"{run_id}.summary.json"
            stdout_path = out_dir / f"{run_id}.stdout.txt"
            stderr_path = out_dir / f"{run_id}.stderr.txt"
            cmd = [
                args.python,
                str(Path(__file__).resolve()),
                "--child",
                str(inst),
                "--timelimit",
                str(args.timelimit),
                "--events",
                str(events_path),
                "--run-id",
                run_id,
                "--summary",
                str(child_summary),
            ]
            env = os.environ.copy()
            if args.hashseed is not None:
                env["PYTHONHASHSEED"] = str(args.hashseed)
            timeout = args.timeout or max(args.timelimit * 2.0 + 30.0, 60.0)
            print(f"[measure] {run_id}  {inst.name}")
            try:
                proc = subprocess.run(
                    cmd, cwd=str(ROOT), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, timeout=timeout,
                )
                stdout_path.write_text(proc.stdout, encoding="utf-8", errors="replace")
                stderr_path.write_text(proc.stderr, encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired as e:
                stdout_path.write_text(e.stdout or "", encoding="utf-8", errors="replace")
                stderr_path.write_text(e.stderr or "", encoding="utf-8", errors="replace")
                _json_dump(child_summary, {
                    "run_id": run_id,
                    "instance": inst.stem,
                    "timelimit": args.timelimit,
                    "elapsed": timeout,
                    "feasible": False,
                    "objective": None,
                    "error": f"subprocess timeout after {timeout:.1f}s",
                })

            if child_summary.exists():
                row = json.loads(child_summary.read_text(encoding="utf-8"))
            else:
                row = {
                    "run_id": run_id,
                    "instance": inst.stem,
                    "feasible": False,
                    "objective": None,
                    "error": "missing child summary",
                }
            summaries.append(row)
            obj = row.get("objective")
            print(f"[measure]   feasible={row.get('feasible')} obj={obj} "
                  f"elapsed={row.get('elapsed')}")

    events = _load_jsonl(events_path)
    events_by_run: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        rid = e.get("run_id")
        if rid:
            events_by_run[rid].append(e)

    by_instance: dict[str, list[dict]] = defaultdict(list)
    for row in summaries:
        by_instance[row.get("instance", "unknown")].append(row)

    reduced = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "out_dir": str(out_dir),
        "events": str(events_path),
        "runs_per_instance": args.runs,
        "timelimit": args.timelimit,
        "instances": [
            _summarize_instance(inst, rows, events_by_run)
            for inst, rows in sorted(by_instance.items())
        ],
    }
    _json_dump(out_dir / "summary.json", reduced)
    (out_dir / "summary.md").write_text(_render_md(reduced), encoding="utf-8")
    print(f"[measure] summary: {out_dir / 'summary.md'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run sequential bimodal measurements.")
    ap.add_argument("instances", nargs="*", help="Instance JSON files")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--timelimit", type=float, default=60.0)
    ap.add_argument("--out", default=None, help="Output directory")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--timeout", type=float, default=None,
                    help="Subprocess timeout per run; default is 2*timelimit+30")
    ap.add_argument("--hashseed", default=None,
                    help="Optional PYTHONHASHSEED for child runs; default leaves it unset")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--events", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--summary", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.child:
        if not args.instances or args.events is None or args.run_id is None or args.summary is None:
            raise SystemExit("--child requires instance, --events, --run-id, --summary")
        args.instance = Path(args.instances[0])
        return _child(args)
    return _parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
