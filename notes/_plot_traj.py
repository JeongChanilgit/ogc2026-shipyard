"""Plot per-instance objective trajectories (obj, z1, z2, z3 vs wall-time),
colour-coded by the OPERATING SEQUENCE (stage) that produced each improvement,
so the segments are visually separable.

Reads results/traj/<inst>.json = {"instance","tl","points":[[t,obj,z1,z2,z3,stage],...]}
(produced by running the solver with OGC_TRAJ=1; see notes/_capture_traj.py).

  python notes/_plot_traj.py --instances prob_4,prob_10,prob_16 --out results/traj/plots
  python notes/_plot_traj.py --instances ALL --grid       # one combined obj grid

Each point is the incumbent AFTER a stage adopted; the curve is a step function
(value held until the next adoption).  Segment colour = the stage of the point it
steps DOWN to, so you can see which sequence bought which drop.
"""
import argparse, json, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
TRAJ = ROOT / "results" / "traj"
ALL20 = [f"prob_{i}" for i in range(1, 21)]

# Stable colour per stage (operating sequence).  Order ~ pipeline order.
STAGE_COLORS = {
    "floor":             "#9e9e9e",
    "search":            "#607d8b",
    "incumbent":         "#455a64",
    "cum_level":         "#1f77b4",
    "cpsat_timing":      "#17becf",
    "bbox_pack":         "#2ca02c",
    "bbox_pack_slab":    "#98df8a",
    "bbox_pack2":        "#2ca02c",
    "crossbay_relocate": "#ff7f0e",
    "exit_pull":         "#bcbd22",
    "reschedule":        "#dbdb8d",
    "shift_tardy":       "#e377c2",
    "tardy_redecode":    "#d62728",
    "multi_reschedule":  "#9467bd",
    "single_move":       "#8c564b",
    "fb_relocate":       "#e41a1c",
    "fb_swap":           "#f781bf",
}
_FALLBACK = ["#393b79", "#637939", "#8c6d31", "#843c39", "#7b4173"]


def color_for(stage, _cache={}, _ix=[0]):
    if stage in STAGE_COLORS:
        return STAGE_COLORS[stage]
    if stage not in _cache:
        _cache[stage] = _FALLBACK[_ix[0] % len(_FALLBACK)]
        _ix[0] += 1
    return _cache[stage]


def load(inst):
    p = TRAJ / f"{inst}.json"
    if not p.exists():
        return None
    return json.load(open(p))


def step_segments(ts, ys, stages):
    """Yield (x0,x1,y0,y1,stage) step segments: horizontal hold then vertical drop."""
    for i in range(1, len(ts)):
        # horizontal hold at previous level, coloured by the stage we are about to
        # step to (so the run-up to a drop is attributed to that sequence)
        yield (ts[i - 1], ts[i], ys[i - 1], ys[i - 1], stages[i])
        # vertical drop
        yield (ts[i], ts[i], ys[i - 1], ys[i], stages[i])


def plot_instance(inst, data, outdir):
    pts = data["points"]
    if not pts:
        return None
    ts = [p[0] for p in pts]
    obj = [p[1] for p in pts]
    z1 = [p[2] if p[2] is not None else float("nan") for p in pts]
    z2 = [p[3] if p[3] is not None else float("nan") for p in pts]
    z3 = [p[4] if p[4] is not None else float("nan") for p in pts]
    stages = [p[5] for p in pts]
    used_stages = []
    for s in stages:
        if s not in used_stages:
            used_stages.append(s)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    panels = [("objective (w1·Z1+w2·Z2+w3·Z3)", obj),
              ("Z1  (tardiness)", z1),
              ("Z2  (workload imbalance)", z2),
              ("Z3  (preference deviation)", z3)]
    for ax, (title, ys) in zip(axes.flat, panels):
        for x0, x1, y0, y1, stg in step_segments(ts, ys, stages):
            ax.plot([x0, x1], [y0, y1], color=color_for(stg), lw=2.0,
                    solid_capstyle="round")
        # markers at each adoption
        for t, y, stg in zip(ts, ys, stages):
            ax.plot(t, y, "o", color=color_for(stg), ms=3.5, zorder=3)
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("wall time (s)")
        ax.grid(alpha=0.25)
        ax.margins(x=0.02)
    handles = [Line2D([0], [0], color=color_for(s), lw=3, label=s)
               for s in used_stages]
    fig.legend(handles=handles, loc="lower center", ncol=min(8, len(handles)),
               fontsize=9, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fin = data["points"][-1]
    fig.suptitle(f"{inst}  —  objective trajectory by operating sequence "
                 f"(final: obj={fin[1]:.0f}  z1={fin[2]:.0f}  z2={fin[3]:.0f}  z3={fin[4]:.0f}"
                 f"  @ {fin[0]:.0f}s,  tl={data.get('tl','?')})",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    out = outdir / f"{inst}_traj.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_grid(insts, outdir):
    fig, axes = plt.subplots(4, 5, figsize=(22, 14))
    seen = []
    for ax, inst in zip(axes.flat, insts):
        data = load(inst)
        if not data or not data["points"]:
            ax.set_title(f"{inst} (no data)"); ax.axis("off"); continue
        pts = data["points"]
        ts = [p[0] for p in pts]; obj = [p[1] for p in pts]
        stages = [p[5] for p in pts]
        for x0, x1, y0, y1, stg in step_segments(ts, obj, stages):
            ax.plot([x0, x1], [y0, y1], color=color_for(stg), lw=1.8)
            if stg not in seen:
                seen.append(stg)
        ax.set_title(f"{inst}  obj {obj[-1]:.0f}", fontsize=9)
        ax.grid(alpha=0.2); ax.margins(x=0.02)
    handles = [Line2D([0], [0], color=color_for(s), lw=3, label=s) for s in seen]
    fig.legend(handles=handles, loc="lower center", ncol=min(9, len(handles)),
               fontsize=9, frameon=False)
    fig.suptitle("OGC2026 — per-instance objective trajectory, coloured by operating sequence",
                 fontsize=14)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    out = outdir / "all_obj_grid.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="ALL")
    ap.add_argument("--out", default=str(TRAJ / "plots"))
    ap.add_argument("--grid", action="store_true")
    a = ap.parse_args()
    insts = ALL20 if a.instances.upper() == "ALL" else \
            [s.strip() for s in a.instances.split(",")]
    outdir = Path(a.out); outdir.mkdir(parents=True, exist_ok=True)
    if a.grid:
        print("grid ->", plot_grid(insts, outdir))
    for inst in insts:
        data = load(inst)
        if data is None:
            print(f"{inst}: no traj data"); continue
        out = plot_instance(inst, data, outdir)
        print(f"{inst}: {out}")


if __name__ == "__main__":
    main()
