"""
visualize.py -- Side-by-side visual comparison of baseline vs our solver.

For a given instance it runs both solvers (or loads pre-computed solution
JSON files), then draws, for each solver:

  * Per-bay SPATIAL layout at the bay's peak-occupancy snapshot -- the moment
    the bay holds the most simultaneously-present blocks.  Block footprints are
    drawn as polygons (layer 0 filled, higher layers outlined) so packing
    density and shape nesting are visible.  Block colors are consistent across
    both solvers so you can track where a block moved.

  * A GANTT timeline (time on x, one row per block, grouped by bay).  Bars run
    from ENTRY to EXIT, coloured by bay.  Each block's due-date is marked; any
    tardy tail (exit beyond due) is hatched red so Z1 is visible at a glance.

Usage:
    python tools/visualize.py instances/example/example_B2_b10.json --timelimit 30
    python tools/visualize.py instances/gen/gen_n40_tight_w1_s9.json --timelimit 60 --out results/cmp.png
    python tools/visualize.py inst.json --baseline-sol b.json --ours-sol o.json   # no re-run

Output: PNG saved under results/ (or --out path).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.patches import Rectangle


# ---------------------------------------------------------------------------
# Solution parsing
# ---------------------------------------------------------------------------

def extract_placements(solution: dict) -> dict[int, dict]:
    """operations dict -> {block_id: {bay, x, y, orient, entry, exit}}."""
    placements: dict[int, dict] = {}
    ops_by_time = solution.get("operations", {})
    for t_str, ops in ops_by_time.items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            rec = placements.setdefault(bid, {})
            if op["type"] == "ENTRY":
                rec.update(
                    bay=op["bay_id"], x=op["x"], y=op["y"],
                    orient=op["orient_idx"], entry=t,
                )
            else:  # EXIT
                rec["exit"] = t
                rec.setdefault("bay", op["bay_id"])
    # Keep only fully-specified placements.
    return {b: r for b, r in placements.items()
            if {"bay", "x", "y", "orient", "entry", "exit"} <= r.keys()}


def peak_snapshot_time(recs: list[dict]) -> int | None:
    """Time at which the most blocks are simultaneously present in a bay."""
    if not recs:
        return None
    candidates = sorted({r["entry"] for r in recs})
    best_t, best_n = candidates[0], -1
    for t in candidates:
        n = sum(1 for r in recs if r["entry"] <= t < r["exit"])
        if n > best_n:
            best_n, best_t = n, t
    return best_t


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _block_color(block_id: int, n_blocks: int):
    cmap = plt.cm.tab20 if n_blocks <= 20 else plt.cm.hsv
    return cmap((block_id % 20) / 20.0 if n_blocks <= 20
                else (block_id % n_blocks) / max(1, n_blocks))


def draw_bay(ax, bay, recs_in_bay, snapshot_t, prob_info, n_blocks):
    """Draw one bay's spatial layout at snapshot_t."""
    from utils import Block

    W, H = bay.width, bay.height
    # Bay outline.
    ax.add_patch(Rectangle((0, 0), W, H, fill=False, edgecolor="black", lw=1.6))
    present = [r for r in recs_in_bay
               if snapshot_t is not None and r["entry"] <= snapshot_t < r["exit"]]
    for r in present:
        bid = r["bid"]
        blk = Block(bid, prob_info["blocks"][bid], x=r["x"], y=r["y"],
                    orient_idx=r["orient"])
        layers = blk.layers_at_pos()
        color = _block_color(bid, n_blocks)
        for li, layer in enumerate(layers):
            if len(layer) < 3:
                continue
            if li == 0:
                ax.add_patch(MplPolygon(layer, closed=True, facecolor=color,
                                        edgecolor="black", alpha=0.6, lw=0.8))
            else:
                ax.add_patch(MplPolygon(layer, closed=True, fill=False,
                                        edgecolor=color, lw=1.0, ls="--"))
        # Label at footprint centroid.
        xs = [v[0] for v in layers[0]]
        ys = [v[1] for v in layers[0]]
        ax.text(sum(xs) / len(xs), sum(ys) / len(ys), str(bid),
                ha="center", va="center", fontsize=8, fontweight="bold")

    load = sum(prob_info["blocks"][r["bid"]]["workload"] for r in recs_in_bay)
    ax.set_title(f"bay {bay.id}  {W}x{H}\n"
                 f"t={snapshot_t}  blocks={len(present)}/{len(recs_in_bay)}  "
                 f"load={load}", fontsize=8)
    ax.set_xlim(-1, W + 1)
    ax.set_ylim(-1, H + 1)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=6)


def draw_gantt(ax, placements, prob_info, n_blocks, title):
    """Gantt of ENTRY->EXIT per block, grouped by bay, due-date + tardiness."""
    items = sorted(placements.items(), key=lambda kv: (kv[1]["bay"], kv[1]["entry"]))
    bay_palette = plt.cm.Set2
    n_bays = len(prob_info["bays"])
    row = 0
    yticks, ylabels = [], []
    last_bay = None
    for bid, r in items:
        bay = r["bay"]
        if bay != last_bay and last_bay is not None:
            ax.axhline(row - 0.5, color="0.6", lw=0.6, ls=":")
        last_bay = bay
        due = prob_info["blocks"][bid]["due_date"]
        entry, exit_t = r["entry"], r["exit"]
        bcol = bay_palette((bay % 8) / 8.0)
        on_time_end = min(exit_t, due)
        ax.barh(row, max(0, on_time_end - entry), left=entry, height=0.7,
                color=bcol, edgecolor="black", lw=0.4)
        if exit_t > due:  # tardy tail
            ax.barh(row, exit_t - due, left=due, height=0.7,
                    color="red", alpha=0.55, hatch="///",
                    edgecolor="darkred", lw=0.4)
        ax.plot([due, due], [row - 0.38, row + 0.38], color="black", lw=1.2)
        yticks.append(row)
        ylabels.append(f"b{bid}(j{bay})")
        row += 1

    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=6)
    ax.invert_yaxis()
    ax.set_xlabel("time", fontsize=8)
    ax.set_title(title, fontsize=9)
    ax.grid(axis="x", color="0.9", lw=0.5)
    # Legend: bay colors + due/tardy markers.
    handles = [Rectangle((0, 0), 1, 1, color=bay_palette((j % 8) / 8.0))
               for j in range(n_bays)]
    labels = [f"bay {j}" for j in range(n_bays)]
    handles.append(Rectangle((0, 0), 1, 1, color="red", alpha=0.55, hatch="///"))
    labels.append("tardy")
    ax.legend(handles, labels, fontsize=6, ncol=min(6, n_bays + 1),
              loc="upper right", framealpha=0.9)


# ---------------------------------------------------------------------------
# Figure assembly
# ---------------------------------------------------------------------------

def _bay_grid_dims(m: int) -> tuple[int, int]:
    cols = max(1, int(m ** 0.5 + 0.999))
    rows = (m + cols - 1) // cols
    return rows, cols


def build_figure(prob_info, results, out_path):
    """results = [(name, solution, report), ...] (one per solver)."""
    from utils import Bay

    bays = [Bay.from_dict(b, j) for j, b in enumerate(prob_info["bays"])]
    m = len(bays)
    n_blocks = len(prob_info["blocks"])
    brows, bcols = _bay_grid_dims(m)

    n_solvers = len(results)
    fig = plt.figure(figsize=(8.5 * n_solvers, 4.0 + 2.6 * brows))
    # Outer: 2 rows (spatial, gantt) x n_solvers cols.
    outer = fig.add_gridspec(2, n_solvers, height_ratios=[2.4 * brows, 3.0],
                             hspace=0.32, wspace=0.16)

    for col, (name, solution, report) in enumerate(results):
        placements = extract_placements(solution)
        # Group by bay with bid attached.
        by_bay: dict[int, list[dict]] = {j: [] for j in range(m)}
        for bid, r in placements.items():
            rec = dict(r, bid=bid)
            by_bay.setdefault(r["bay"], []).append(rec)

        # --- spatial sub-grid ---
        sp = outer[0, col].subgridspec(brows, bcols, hspace=0.5, wspace=0.3)
        for j in range(m):
            ax = fig.add_subplot(sp[j // bcols, j % bcols])
            recs = by_bay.get(j, [])
            draw_bay(ax, bays[j], recs, peak_snapshot_time(recs),
                     prob_info, n_blocks)
        # hide unused spatial cells
        for j in range(m, brows * bcols):
            ax = fig.add_subplot(sp[j // bcols, j % bcols])
            ax.axis("off")

        # --- gantt ---
        gax = fig.add_subplot(outer[1, col])
        feas = report.get("feasible")
        obj = report.get("objective")
        z1 = report.get("obj1")
        z2 = report.get("obj2")
        z3 = report.get("obj3")
        feas_tag = "FEASIBLE" if feas else "INFEASIBLE"
        title = (f"{name}   [{feas_tag}]   obj={obj:.2f}\n"
                 f"Z1(tard)={z1:.1f}  Z2(imbal)={z2:.2f}  Z3(pref)={z3:.1f}"
                 if obj is not None else f"{name}   [{feas_tag}]")
        draw_gantt(gax, placements, prob_info, n_blocks, title)

    # Suptitle with comparison.
    w = prob_info.get("weights", {})
    name0, _, rep0 = results[0]
    sub = (f"{prob_info.get('name','instance')}   "
           f"n={n_blocks} m={m}   w1={w.get('w1')} w2={w.get('w2')} w3={w.get('w3')}")
    if len(results) == 2 and rep0.get("objective") is not None \
            and results[1][2].get("objective") is not None:
        o0 = rep0["objective"]
        o1 = results[1][2]["objective"]
        if abs(o0) > 1e-9:
            sub += f"    |    {name0}={o0:.2f}  vs  {results[1][0]}={o1:.2f}  " \
                   f"({100.0*(o0-o1)/o0:+.1f}%)"
    fig.suptitle(sub, fontsize=12, fontweight="bold")
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"[visualize] saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _run_and_report(solver_fn, prob_info, timelimit):
    from utils import check_feasibility
    t0 = time.perf_counter()
    sol = solver_fn(prob_info, timelimit)
    elapsed = time.perf_counter() - t0
    report = check_feasibility(prob_info, sol)
    print(f"[visualize]   {solver_fn.__name__}: feasible={report.get('feasible')} "
          f"obj={report.get('objective')} elapsed={elapsed:.1f}s")
    return sol, report


def main() -> int:
    ap = argparse.ArgumentParser(description="Visualize baseline vs ours.")
    ap.add_argument("instance", help="Instance JSON path")
    ap.add_argument("--timelimit", type=float, default=30.0)
    ap.add_argument("--out", default=None, help="Output PNG path")
    ap.add_argument("--baseline-sol", default=None,
                    help="Pre-computed baseline solution JSON (skip re-run)")
    ap.add_argument("--ours-sol", default=None,
                    help="Pre-computed ours solution JSON (skip re-run)")
    args = ap.parse_args()

    from utils import check_feasibility

    inst_path = Path(args.instance)
    prob_info = json.loads(inst_path.read_text(encoding="utf-8"))

    results = []

    if args.baseline_sol:
        sol = json.loads(Path(args.baseline_sol).read_text(encoding="utf-8"))
        results.append(("baseline", sol, check_feasibility(prob_info, sol)))
    else:
        from baseline_greedy import greedyalgorithm
        sol, rep = _run_and_report(greedyalgorithm, prob_info, args.timelimit)
        results.append(("baseline", sol, rep))

    if args.ours_sol:
        sol = json.loads(Path(args.ours_sol).read_text(encoding="utf-8"))
        results.append(("ours", sol, check_feasibility(prob_info, sol)))
    else:
        from myalgorithm import algorithm
        sol, rep = _run_and_report(algorithm, prob_info, args.timelimit)
        results.append(("ours", sol, rep))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        results_dir = ROOT / "results"
        results_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = results_dir / f"viz_{inst_path.stem}_{ts}.png"

    build_figure(prob_info, results, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
