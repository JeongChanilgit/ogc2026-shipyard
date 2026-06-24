"""analyze_run.py -- turn an OGC 2026 solver trace into a Claude-readable report.

The solver (src/myalgorithm.py) emits a trace JSON when OGC_TRACE is set (see
src/instrument.py).  This tool reads one such trace and explains, in plain
language, *how the solution evolved* and *where the algorithm is leaving score
on the table*.  Its "Diagnostics" section is a ready-made, severity-ranked list
of improvement points: the intended workflow is "run traced -> analyze -> read
Diagnostics -> fix -> repeat".

Usage:
    python tools/analyze_run.py                      # newest trace in results/traces
    python tools/analyze_run.py results/traces/<f>.json
    python tools/analyze_run.py results/traces        # newest in that dir
    python tools/analyze_run.py results/traces --all  # cross-run fleet summary
    python tools/analyze_run.py <trace> --plot        # also save a trajectory PNG

Writes the report to results/reports/ and prints it to stdout.  Pure stdlib for
parsing; matplotlib is imported lazily only for --plot.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

# Windows consoles (cp949/cp1252) can't encode the em-dash/arrow glyphs used in
# the report; the report file is always UTF-8, so only soften the console echo.
try:  # pragma: no cover - platform dependent
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "results" / "traces"
REPORT_DIR = ROOT / "results" / "reports"
FIG_DIR = ROOT / "figures"

# Severity ordering for sorting / display.
SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
SEV_ICON = {"CRITICAL": "[X]", "HIGH": "[!]", "MEDIUM": "[~]", "LOW": "[.]", "INFO": "[i]"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _newest(d: Path) -> Path | None:
    files = glob.glob(str(d / "*.json"))
    if not files:
        return None
    return Path(max(files, key=os.path.getmtime))


def _resolve_trace(arg: str | None) -> Path | None:
    if arg is None:
        return _newest(TRACE_DIR)
    p = Path(arg)
    if p.is_dir():
        return _newest(p)
    if p.is_file():
        return p
    return None


def load_trace(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _fmt(v, d=2):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        if v == float("inf"):
            return "inf"
        return f"{v:,.{d}f}"
    return str(v)


def _events_of(events, kind):
    return [e for e in events if e.get("kind") == kind]


def _first(events, kind):
    for e in events:
        if e.get("kind") == kind:
            return e
    return None


# ---------------------------------------------------------------------------
# Structured view of one trace
# ---------------------------------------------------------------------------

class RunView:
    """Parses a trace into the fields the report and diagnostics need."""

    def __init__(self, trace: dict, source: str = ""):
        self.source = source
        self.meta = trace.get("meta", {})
        self.events = trace.get("events", [])
        self.weights = self.meta.get("weights", {})

        self.phases = {e["name"]: e for e in _events_of(self.events, "phase")}
        self.candidates = _events_of(self.events, "candidate")
        self.cand_by_label = {c.get("label"): c for c in self.candidates}
        self.seeds = _events_of(self.events, "seed")
        self.cpsat = _first(self.events, "cpsat")
        self.search_start = _first(self.events, "search_start")
        self.search_end = _first(self.events, "search_end")
        self.search_skipped = _first(self.events, "search_skipped")
        self.snaps = _events_of(self.events, "search_snap")
        self.improves = _events_of(self.events, "search_improve")
        self.ladder = _first(self.events, "ladder")
        self.gate_checks = _events_of(self.events, "gate_check")
        self.gate_skips = _events_of(self.events, "gate_skip")
        self.final = _first(self.events, "final")
        self.optimize_error = _first(self.events, "optimize_error")

    # -- derived ------------------------------------------------------------
    @property
    def returned_label(self):
        return (self.final or {}).get("returned_label")

    @property
    def returned_obj(self):
        return (self.final or {}).get("objective")

    @property
    def elapsed(self):
        return (self.final or {}).get("elapsed")

    @property
    def timelimit(self):
        return self.meta.get("timelimit")

    def ladder_obj(self, label):
        if not self.ladder:
            return None
        for r in self.ladder.get("ranked", []):
            if r.get("label") == label:
                v = r.get("quick_obj")
                return None if v == float("inf") else v
        return None

    def gate_check_for(self, label):
        for g in self.gate_checks:
            if g.get("label") == label:
                return g
        return None

    @property
    def weighted_components(self):
        """(c1, c2, c3) weighted final-objective contributions, from the gate
        check of the returned candidate (authoritative) or search_end."""
        g = self.gate_check_for(self.returned_label) if self.returned_label else None
        z = None
        if g and g.get("objective") is not None:
            # gate_check has the true objective but not the components; pull Z
            # from search_end when the returned candidate is "search".
            pass
        se = self.search_end
        if self.returned_label == "search" and se:
            z = (se.get("best_z1"), se.get("best_z2"), se.get("best_z3"))
        return z


# ---------------------------------------------------------------------------
# Diagnostics -- automated, severity-ranked improvement points
# ---------------------------------------------------------------------------

def diagnose(v: RunView) -> list[dict]:
    f: list[dict] = []

    def add(sev, title, detail, suggestion=""):
        f.append({"severity": sev, "title": title, "detail": detail,
                  "suggestion": suggestion})

    base = v.cand_by_label.get("baseline")
    base_obj = v.ladder_obj("baseline")
    search_obj = v.ladder_obj("search")
    ret_obj = v.returned_obj

    # D1 -- returned worse than the baseline candidate (invariant §4.4 breach).
    if base_obj is not None and ret_obj is not None and ret_obj > base_obj + 1e-6:
        add("CRITICAL",
            "Returned solution is WORSE than the baseline candidate (invariant §4.4)",
            f"returned `{v.returned_label}` obj={_fmt(ret_obj)} but the baseline "
            f"candidate had obj={_fmt(base_obj)}.",
            "The gate must never return worse-than-baseline when baseline is "
            "feasible. Check whether baseline was verified before the budget ran "
            "out, or force baseline into the verified set.")

    # D2 -- no baseline quality floor.
    if base is None or base.get("status") not in ("added",):
        st = base.get("status") if base else "absent"
        add("CRITICAL" if base is None else "HIGH",
            "Baseline candidate not in the pool",
            f"baseline candidate status = `{st}`"
            + (f" ({base.get('error')})" if base and base.get("error") else "")
            + ". Without it there is no proven quality/safety floor.",
            "Ensure greedyalgorithm() runs and is added; if it is too slow, give "
            "it a smaller budget rather than dropping it.")

    # D3 -- gate fell back (verification budget exhausted -> trivial/fallback).
    reason = (v.final or {}).get("reason", "")
    if "exhausted" in reason or v.returned_label in ("trivial", "fallback"):
        add("HIGH",
            "Gate fell back to the serialized floor (verification budget exhausted)",
            f"returned `{v.returned_label}` (reason: {reason}). The good "
            f"candidates were never verified in time.",
            "Lower the search/decode budget or improve the check_cost estimate so "
            "check_feasibility runs before hard_stop.")
    if v.gate_skips:
        add("MEDIUM",
            "A candidate was skipped at the gate for lack of time",
            f"{len(v.gate_skips)} gate skip(s): "
            + ", ".join(f"{g.get('label')}({g.get('reason')})" for g in v.gate_skips),
            "The verification window is too tight; reserve more time for the gate.")

    # D4 -- elapsed close to the timelimit (timeout proximity -> -1 risk).
    if v.elapsed is not None and v.timelimit:
        frac = v.elapsed / v.timelimit
        if frac > 0.85:
            add("HIGH",
                "Wall-clock dangerously close to the time limit",
                f"elapsed {_fmt(v.elapsed)}s = {frac*100:.0f}% of the {v.timelimit:.0f}s "
                f"limit. The spec timeout boundary is 85%.",
                "Tighten the time guard; the server kills at 100% for a -1.")
        elif frac > 0.78:
            add("MEDIUM",
                "Wall-clock near the planned 80% target",
                f"elapsed {_fmt(v.elapsed)}s = {frac*100:.0f}% of the limit.",
                "Acceptable but little headroom; watch larger instances.")

    # D5 / D6 / D7 -- ALNS behaviour.
    se = v.search_end
    ss = v.search_start
    if v.search_skipped and not se:
        add("MEDIUM",
            "Local search was skipped entirely",
            f"reason: {v.search_skipped.get('reason')}. The result is the raw "
            f"seed decode with no improvement.",
            "On large/dense instances the per-move re-decode is estimated too "
            "costly. A faster geometry kernel (M2) would unlock search here.")
    if se:
        n_imp = se.get("n_improve", 0)
        iters = se.get("iters", 0)
        restarts = se.get("restarts", 0)
        start_obj = ss.get("obj") if ss else None
        end_obj = se.get("best_obj")
        if n_imp == 0:
            add("MEDIUM",
                "Local search found no improvement over the seed",
                f"{iters} iterations, 0 improving moves. Seed obj "
                f"{_fmt(start_obj)} == final {_fmt(end_obj)}.",
                "Seeds may already be locally optimal for these neighbourhoods, "
                "or the neighbourhoods don't reach the gain. Add a regime-aware "
                "operator (e.g. preference-repair for w3, tardiness-repair for w1).")
        if iters and restarts and restarts > 0.5 * iters / max(1, 60):
            # restarts fire after ~60 stalled iters; many restarts => thrash.
            add("MEDIUM",
                "Local search thrashes (restarts to best very frequently)",
                f"{restarts} restarts over {iters} iters: it finds its best early "
                f"then spends the rest of the budget unable to escape.",
                "Either stop early and reallocate time (parallel restarts / more "
                "seeds), or strengthen diversification (larger destroy, accept "
                "plateaus longer).")
        # operator calibration
        names = se.get("op_names", [])
        uses = se.get("op_uses", [])
        imps = se.get("op_improves", [])
        if names and uses:
            tot = sum(uses) or 1
            for i, nm in enumerate(names):
                share = uses[i] / tot
                imp_i = imps[i] if i < len(imps) else 0
                if uses[i] >= 50 and imp_i == 0:
                    add("LOW",
                        f"Operator `{nm}` never improved",
                        f"used {uses[i]} times ({share*100:.0f}% of moves), 0 "
                        f"improvements.",
                        "Roulette weights will down-rank it, but consider whether "
                        "it is wired correctly for this regime.")

    # D8 -- low iteration count relative to budget (decode bottleneck).
    if se and v.timelimit:
        iters = se.get("iters", 0)
        if v.meta.get("n_blocks", 0) >= 80 and iters and iters < 200:
            add("MEDIUM",
                "Very few search iterations on a large instance",
                f"only {iters} ALNS iterations for n={v.meta.get('n_blocks')} "
                f"blocks: per-move re-decode dominates the budget.",
                "This is the throughput wall the geometry kernel (M2) targets.")

    # D9 -- search introduced tardiness vs a Z1=0 seed (the s17/s10 pattern).
    seed_z1 = None
    for s in v.seeds:
        if s.get("status") == "decoded" and s.get("z1") is not None:
            seed_z1 = 0.0 if seed_z1 is None else seed_z1
            seed_z1 = min(seed_z1, s.get("z1"))
    if se and seed_z1 is not None:
        end_z1 = se.get("best_z1")
        if end_z1 is not None and end_z1 > seed_z1 + 1e-6 and end_z1 > 1.0:
            add("HIGH",
                "Search traded tardiness (Z1) up while chasing Z2/Z3",
                f"best decode had Z1={_fmt(seed_z1)} among seeds but search ended "
                f"at Z1={_fmt(end_z1)}. On a w1-light instance the weighted total "
                f"can still rise above baseline.",
                "Acceptance uses the *weighted* objective, so a tiny w1 lets Z1 "
                "balloon. Bound Z1 increases, or keep the min-Z1 incumbent too.")

    # D10 -- seeds skipped due to decode cost.
    skipped_cost = [s for s in v.seeds if s.get("reason") == "decode_cost"]
    if skipped_cost:
        add("INFO",
            "Some seeds were skipped because decoding would overrun the budget",
            ", ".join(f"{s.get('name')}(est {_fmt(s.get('decode_est'))}s)"
                      for s in skipped_cost),
            "Confirms decode throughput is the binding constraint on big inputs.")

    # D11 -- objective composition: where is the score going?
    z = v.weighted_components
    if z and all(x is not None for x in z) and v.weights:
        w1 = v.weights.get("w1", 1); w2 = v.weights.get("w2", 1); w3 = v.weights.get("w3", 1)
        c1, c2, c3 = w1 * z[0], w2 * z[1], w3 * z[2]
        tot = (c1 + c2 + c3) or 1.0
        parts = sorted([("Z1 tardiness", c1), ("Z2 imbalance", c2),
                        ("Z3 preference", c3)], key=lambda kv: -kv[1])
        dom, domv = parts[0]
        if domv / tot > 0.5:
            add("INFO",
                f"Objective is dominated by {dom} ({domv/tot*100:.0f}% of the total)",
                f"weighted: Z1={_fmt(c1)}, Z2={_fmt(c2)}, Z3={_fmt(c3)}.",
                f"Focused gains on {dom} have the highest leverage for this "
                f"instance's weights.")

    # D12 -- cpsat status (informational).
    if v.cpsat and v.cpsat.get("status") in ("none", "skipped"):
        add("INFO",
            f"CP-SAT seed not used ({v.cpsat.get('status')})",
            f"reason: {v.cpsat.get('reason', 'n/a')}.",
            "Heuristic seeds carried the run; fine unless Z2 balance is poor.")

    if v.optimize_error:
        add("HIGH",
            "The optimisation block raised an exception (was caught)",
            f"{v.optimize_error.get('error')}",
            "Search likely did nothing; the result is a seed/baseline fallback.")

    f.sort(key=lambda d: SEV_RANK.get(d["severity"], 9))
    return f


# ---------------------------------------------------------------------------
# Report rendering (markdown)
# ---------------------------------------------------------------------------

def render_report(v: RunView, findings: list[dict], plot_path: str | None) -> str:
    m = v.meta
    L: list[str] = []
    L.append(f"# Run analysis — {m.get('instance', '?')}")
    L.append("")
    L.append(f"_source trace: `{v.source}`_")
    L.append("")

    # -- 1. Summary ---------------------------------------------------------
    w = v.weights
    L.append("## 1. Summary")
    L.append("")
    L.append(f"- **Instance**: {m.get('instance')}  (n={m.get('n_blocks')} blocks, "
             f"m={m.get('n_bays')} bays)")
    L.append(f"- **Weights**: w1={w.get('w1')}, w2={w.get('w2')}, w3={w.get('w3')}  "
             f"→ dominant **{m.get('weight_dominant')}**")
    if m.get("density") is not None:
        L.append(f"- **Packing density** (Σblock-bbox / Σbay-area): "
                 f"{_fmt(m.get('density'), 3)}")
    L.append(f"- **Time limit**: {_fmt(v.timelimit, 1)}s   |   "
             f"**elapsed**: {_fmt(v.elapsed, 2)}s "
             f"({(v.elapsed/v.timelimit*100):.0f}% of limit)"
             if v.elapsed and v.timelimit else
             f"- **Time limit**: {_fmt(v.timelimit, 1)}s")
    L.append(f"- **Returned**: `{v.returned_label}`  obj=**{_fmt(v.returned_obj)}**  "
             f"(reason: {(v.final or {}).get('reason')})")
    L.append("")

    # -- 2. Phase timings ---------------------------------------------------
    L.append("## 2. Phase timings")
    L.append("")
    L.append("| phase | seconds |")
    L.append("|---|--:|")
    for name in ("trivial", "baseline", "cpsat", "seeds_decode", "search", "gate"):
        ph = v.phases.get(name)
        if ph:
            L.append(f"| {name} | {_fmt(ph.get('seconds'), 3)} |")
    b = m.get("budget", {})
    if b:
        L.append("")
        L.append(f"Budget (s from start): work_deadline={_fmt(b.get('work_deadline_s'),1)}, "
                 f"hard_stop={_fmt(b.get('hard_stop_s'),1)}, "
                 f"check_cost_est={_fmt(b.get('check_cost_est_s'),2)}")
    L.append("")

    # -- 3. Seeds -----------------------------------------------------------
    L.append("## 3. Seeds (Layer-1 assignments)")
    L.append("")
    if v.seeds:
        L.append("| seed | status | obj | Z1 | Z2 | Z3 |")
        L.append("|---|---|--:|--:|--:|--:|")
        for s in v.seeds:
            L.append(f"| {s.get('name')} | {s.get('status')} | {_fmt(s.get('obj'))} "
                     f"| {_fmt(s.get('z1'))} | {_fmt(s.get('z2'))} | {_fmt(s.get('z3'))} |")
    else:
        L.append("_no seed events_")
    L.append("")

    # -- 4. ALNS behaviour --------------------------------------------------
    L.append("## 4. Local search (assignment-level ALNS)")
    L.append("")
    if v.search_skipped and not v.search_end:
        L.append(f"Search was **skipped** — reason: `{v.search_skipped.get('reason')}`.")
    elif v.search_end:
        se = v.search_end
        ss = v.search_start or {}
        start = ss.get("obj")
        end = se.get("best_obj")
        gain = (start - end) if (start is not None and end is not None) else None
        gpct = (gain / start * 100) if (gain is not None and start) else None
        L.append(f"- obj **{_fmt(start)} → {_fmt(end)}**"
                 + (f"  (improved {_fmt(gain)}, {gpct:.1f}%)" if gpct is not None else ""))
        L.append(f"- iterations: **{se.get('iters')}**, improving moves: "
                 f"**{se.get('n_improve')}**, restarts: **{se.get('restarts')}**")
        L.append(f"- moves: accepts={se.get('accepts')}, rejects={se.get('rejects')}, "
                 f"null(no-op)={se.get('nulls')}")
        names = se.get("op_names", [])
        uses = se.get("op_uses", [])
        accs = se.get("op_accepts", [])
        imps = se.get("op_improves", [])
        if names:
            L.append("")
            L.append("| operator | uses | accepts | improves |")
            L.append("|---|--:|--:|--:|")
            for i, nm in enumerate(names):
                L.append(f"| {nm} | {uses[i] if i < len(uses) else '?'} "
                         f"| {accs[i] if i < len(accs) else '?'} "
                         f"| {imps[i] if i < len(imps) else '?'} |")
        if v.improves:
            last = v.improves[-1]
            L.append("")
            L.append(f"- last improvement at t={_fmt(last.get('t_rel'),2)}s "
                     f"(iter {last.get('iter')}) via `{last.get('op')}`")
    else:
        L.append("_no search events_")
    L.append("")
    if plot_path:
        L.append(f"![objective trajectory]({plot_path})")
        L.append("")

    # -- 5. Candidate ladder & gate ----------------------------------------
    L.append("## 5. Candidate ladder & feasibility gate")
    L.append("")
    if v.ladder:
        L.append("| rank | candidate | quick_obj | gate result |")
        L.append("|--:|---|--:|---|")
        for i, r in enumerate(v.ladder.get("ranked", [])):
            lab = r.get("label")
            g = v.gate_check_for(lab)
            if g is None:
                gr = "not checked"
            elif g.get("feasible") is True:
                gr = f"FEASIBLE → returned (obj {_fmt(g.get('objective'))})"
            elif g.get("feasible") is False:
                gr = f"infeasible (stage {g.get('stage')})"
            else:
                gr = f"error: {g.get('error')}"
            qv = r.get("quick_obj")
            L.append(f"| {i+1} | {lab} | "
                     f"{_fmt(None if qv == float('inf') else qv)} | {gr} |")
    else:
        L.append("_no ladder event_")
    L.append("")

    # -- 6. Diagnostics -----------------------------------------------------
    L.append("## 6. Diagnostics — improvement points")
    L.append("")
    if not findings:
        L.append("_No issues detected. This run looks healthy._")
    else:
        for d in findings:
            L.append(f"### {SEV_ICON.get(d['severity'],'')} {d['severity']}: {d['title']}")
            L.append("")
            L.append(f"{d['detail']}")
            if d.get("suggestion"):
                L.append("")
                L.append(f"> **Fix idea:** {d['suggestion']}")
            L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Plot (optional)
# ---------------------------------------------------------------------------

def make_plot(v: RunView, out_path: Path) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    if not v.snaps and not v.improves:
        return None
    try:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        if v.snaps:
            ts = [s.get("t") for s in v.snaps]
            cur = [s.get("cur") for s in v.snaps]
            best = [s.get("best") for s in v.snaps]
            ax.plot(ts, cur, lw=0.8, alpha=0.5, label="current obj")
            ax.plot(ts, best, lw=1.6, label="best obj")
        if v.improves:
            it = [e.get("t") for e in v.improves]
            io = [e.get("obj") for e in v.improves]
            ax.scatter(it, io, s=18, color="red", zorder=5, label="improvement")
        ax.set_xlabel("seconds since start")
        ax.set_ylabel("objective (true)")
        ax.set_title(f"ALNS trajectory — {v.meta.get('instance','?')}")
        ax.legend(loc="best", fontsize=8)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=110)
        plt.close(fig)
        return os.path.relpath(out_path, REPORT_DIR)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Batch / fleet summary
# ---------------------------------------------------------------------------

def fleet_summary(trace_dir: Path) -> str:
    files = sorted(glob.glob(str(trace_dir / "*.json")), key=os.path.getmtime)
    if not files:
        return f"_no traces in {trace_dir}_"
    L = ["# Fleet diagnostics summary", "",
         f"_{len(files)} trace(s) in `{trace_dir}`_", "",
         "| instance | returned | obj | elapsed% | top finding |",
         "|---|---|--:|--:|---|"]
    sev_counter: dict[str, int] = {}
    for fp in files:
        try:
            v = RunView(load_trace(Path(fp)), source=os.path.basename(fp))
        except Exception:
            continue
        finds = diagnose(v)
        for d in finds:
            sev_counter[d["severity"]] = sev_counter.get(d["severity"], 0) + 1
        top = finds[0] if finds else None
        epct = (f"{v.elapsed/v.timelimit*100:.0f}%"
                if v.elapsed and v.timelimit else "N/A")
        L.append(f"| {v.meta.get('instance','?')} | {v.returned_label} "
                 f"| {_fmt(v.returned_obj)} | {epct} | "
                 f"{(SEV_ICON.get(top['severity'],'')+' '+top['title']) if top else '—'} |")
    L.append("")
    L.append("**Finding counts across fleet:** " +
             ", ".join(f"{k}={sev_counter[k]}" for k in
                       sorted(sev_counter, key=lambda s: SEV_RANK.get(s, 9))))
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze an OGC 2026 solver trace.")
    ap.add_argument("trace", nargs="?", default=None,
                    help="Trace JSON file or directory (default: newest in results/traces)")
    ap.add_argument("--all", action="store_true",
                    help="Treat the path as a directory and emit a fleet summary")
    ap.add_argument("--plot", action="store_true",
                    help="Also save an ALNS trajectory PNG to figures/")
    ap.add_argument("--quiet", action="store_true", help="Do not echo the report")
    args = ap.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())

    if args.all:
        d = Path(args.trace) if args.trace else TRACE_DIR
        report = fleet_summary(d)
        out = REPORT_DIR / f"fleet_{stamp}.md"
        out.write_text(report, encoding="utf-8")
        if not args.quiet:
            print(report)
        print(f"\n[analyze_run] fleet summary saved: {out.relative_to(ROOT)}")
        return 0

    path = _resolve_trace(args.trace)
    if path is None:
        print("[analyze_run] no trace found. Run with OGC_TRACE=1 first, e.g.:")
        print("    python tools/run_local.py instances/example/example_B2_b10.json "
              "--timelimit 30 --trace --analyze")
        return 1

    trace = load_trace(path)
    v = RunView(trace, source=os.path.relpath(path, ROOT))
    findings = diagnose(v)

    plot_rel = None
    if args.plot:
        plot_rel = make_plot(v, FIG_DIR / f"traj_{v.meta.get('instance','run')}_{stamp}.png")

    report = render_report(v, findings, plot_rel)
    safe = "".join(c if c.isalnum() or c in "._-" else "_"
                   for c in str(v.meta.get("instance", "run")))[:60]
    out = REPORT_DIR / f"report_{safe}_{stamp}.md"
    out.write_text(report, encoding="utf-8")

    if not args.quiet:
        print(report)
    print(f"\n[analyze_run] report saved: {out.relative_to(ROOT)}")
    crit = [d for d in findings if d["severity"] in ("CRITICAL", "HIGH")]
    if crit:
        print(f"[analyze_run] {len(crit)} CRITICAL/HIGH finding(s) — see Diagnostics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
