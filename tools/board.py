"""Progress DASHBOARD CLI for OGC2026 -- one view of Z1/Z2/Z3/time over all 20
train instances.

Two modes:

  CACHED (default, fast):
      python tools/board.py --sols results
    For each train instance, find a solution JSON in --sols whose filename stem
    CONTAINS the instance name (prefer the most-recently-modified on ties),
    score it with the official check_feasibility, and tabulate.  Instances with
    no matching file show "-".

  RUN:
      python tools/board.py --run --timelimit 60 [--instances prob_11,prob_13]
    Run the solver fresh per instance in an ISOLATED subprocess via the existing
    tools/run_solver_once.py runner (conda run -n ogc2025 ...), parse its JSON
    line, and tabulate.  Sequential by default; --conc N runs up to N at once.

Output (both modes): a console table (one row per instance) + a summary footer.
Optional --json PATH writes structured results; --html PATH writes a
self-contained dark-theme page.

Console output is plain ASCII (Windows cp949 console).  The HTML file is UTF-8.

This tool is READ-ONLY w.r.t. the solver core and ogc_analysis.py.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ogc_analysis as A  # noqa: E402

ROOT = Path(A.ROOT)


# --------------------------------------------------------------------------- #
# Cached-mode: match a solution file to an instance name
# --------------------------------------------------------------------------- #
def find_solution_file(sols_dir: str, name: str) -> str | None:
    """Return the path of the solution JSON in ``sols_dir`` whose filename stem
    CONTAINS ``name`` (e.g. 'prob_13' matches '_z0_prob_13.json').  If several
    match, prefer the most recently modified.  Only the immediate directory is
    scanned (non-recursive) to avoid pulling traces/subdir artefacts."""
    d = Path(sols_dir)
    if not d.is_dir():
        return None
    matches = []
    for f in glob.glob(str(d / "*.json")):
        if name in Path(f).stem:
            matches.append(f)
    if not matches:
        return None
    matches.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return matches[0]


# --------------------------------------------------------------------------- #
# Per-instance evaluation (cached and run)
# --------------------------------------------------------------------------- #
def _base_row(name: str, prob: dict) -> dict:
    w = prob.get("weights", {}) or {}
    return {
        "instance": name,
        "n_blk": len(prob.get("blocks", [])),
        "n_bay": len(prob.get("bays", [])),
        "w1": w.get("w1"), "w2": w.get("w2"), "w3": w.get("w3"),
        "feasible": None,
        "obj1": None, "obj2": None, "obj3": None, "objective": None,
        "time_s": None,
        "sol_file": None,
        "status": "missing",
    }


def eval_cached(name: str, sols_dir: str) -> dict:
    """Score a cached solution for one instance.  Never raises; failures are
    recorded in the row's status."""
    prob = A.load_instance(name)
    row = _base_row(name, prob)
    path = find_solution_file(sols_dir, name)
    if path is None:
        return row
    row["sol_file"] = path
    try:
        sol = A.load_solution(path)
        rep = A.score(prob, sol)
        feas = bool(rep.get("feasible"))
        row.update({
            "feasible": feas,
            "obj1": rep.get("obj1"),
            "obj2": rep.get("obj2"),
            "obj3": rep.get("obj3"),
            "objective": rep.get("objective"),
            "status": "ok" if feas else "infeasible",
        })
    except Exception as e:  # corrupt / mismatched solution file
        row["status"] = f"error: {type(e).__name__}: {e}"
        row["feasible"] = False
    return row


def eval_run(name: str, timelimit: float) -> dict:
    """Run the solver fresh for one instance via run_solver_once.py in an
    isolated subprocess.  Never raises; failures land in the row status."""
    prob = A.load_instance(name)
    row = _base_row(name, prob)
    inst = A.instance_path(name)
    out_sol = ROOT / "results" / f"_board_{name}.json"
    out_res = ROOT / "results" / f"_board_{name}_result.json"
    out_sol.parent.mkdir(parents=True, exist_ok=True)
    row["sol_file"] = str(out_sol)

    cmd = [
        "conda", "run", "-n", "ogc2025", "python",
        str(ROOT / "tools" / "run_solver_once.py"),
        str(inst), "--solver", "our",
        "--timelimit", str(timelimit),
        "--save-sol", str(out_sol),
        "--out", str(out_res),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True,
            timeout=timelimit + 600,
        )
    except subprocess.TimeoutExpired:
        row["status"] = "timeout"
        row["feasible"] = False
        return row

    parsed = _parse_runner_json(proc.stdout)
    if parsed is None:
        tail = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
        row["status"] = "no-json: " + tail[-200:]
        row["feasible"] = False
        return row

    feas = bool(parsed.get("feasible"))
    row.update({
        "feasible": feas,
        "obj1": parsed.get("obj1"),
        "obj2": parsed.get("obj2"),
        "obj3": parsed.get("obj3"),
        "objective": parsed.get("objective"),
        "time_s": parsed.get("elapsed"),
        "status": "ok" if feas else (parsed.get("error") or "infeasible"),
    })
    return row


def _parse_runner_json(stdout: str) -> dict | None:
    """run_solver_once.py prints a single JSON object as its last meaningful
    line.  Scan stdout lines from the bottom for the first that parses as a JSON
    object carrying the expected keys."""
    if not stdout:
        return None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and "feasible" in obj:
            return obj
    return None


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def _fmt_num(v) -> str:
    """Render a numeric cell as ASCII; '-' for None."""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "Y" if v else "N"
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return f"{v:.3f}"
    return str(v)


def _fmt_feas(v) -> str:
    if v is None:
        return "-"
    return "Y" if v else "N"


COLUMNS = [
    ("instance", "instance", "left"),
    ("n_blk", "n_blk", "right"),
    ("n_bay", "n_bay", "right"),
    ("feasible", "feas", "right"),
    ("obj1", "Z1", "right"),
    ("obj2", "Z2", "right"),
    ("obj3", "Z3", "right"),
    ("objective", "weighted_obj", "right"),
    ("time_s", "time_s", "right"),
]


def render_table(rows: list, show_time: bool) -> str:
    cols = [c for c in COLUMNS if show_time or c[0] != "time_s"]
    # Build cell text.
    body = []
    for r in rows:
        cells = []
        for key, _hdr, _align in cols:
            if key == "feasible":
                cells.append(_fmt_feas(r.get(key)))
            elif key == "instance":
                cells.append(str(r.get(key)))
            elif key == "time_s" and not show_time:
                cells.append("-")
            else:
                cells.append(_fmt_num(r.get(key)))
        body.append(cells)
    headers = [hdr for _k, hdr, _a in cols]
    widths = [len(h) for h in headers]
    for cells in body:
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], len(c))

    def fmt_line(cells):
        out = []
        for i, c in enumerate(cells):
            align = cols[i][2]
            out.append(c.ljust(widths[i]) if align == "left"
                       else c.rjust(widths[i]))
        return "  ".join(out)

    sep = "  ".join("-" * w for w in widths)
    lines = [fmt_line(headers), sep]
    lines.extend(fmt_line(c) for c in body)
    return "\n".join(lines)


def render_summary(rows: list) -> str:
    total = len(rows)
    scored = [r for r in rows if r.get("status") != "missing"]
    feasible = [r for r in scored if r.get("feasible")]
    z1_zero = [r for r in feasible
               if r.get("obj1") is not None and float(r["obj1"]) == 0.0]
    z1_pos = [r for r in feasible
              if r.get("obj1") is not None and float(r["obj1"]) > 0.0]
    z1_pos.sort(key=lambda r: float(r["obj1"]), reverse=True)

    sum_z1 = sum(float(r["obj1"]) for r in feasible
                 if r.get("obj1") is not None)
    sum_obj = sum(float(r["objective"]) for r in feasible
                  if r.get("objective") is not None)

    lines = []
    lines.append("SUMMARY")
    lines.append("  feasible        : {0} / {1}".format(len(feasible), total))
    lines.append("  scored (have sol): {0} / {1}".format(len(scored), total))
    lines.append("  Z1 == 0         : {0}".format(len(z1_zero)))
    if z1_pos:
        parts = ["{0}={1}".format(r["instance"], _fmt_num(r["obj1"]))
                 for r in z1_pos]
        lines.append("  Z1 > 0 ({0})    : {1}".format(len(z1_pos),
                                                      ", ".join(parts)))
    else:
        lines.append("  Z1 > 0 (0)     : none")
    lines.append("  sum Z1          : {0}".format(_fmt_num(sum_z1)))
    lines.append("  sum weighted_obj: {0}".format(_fmt_num(sum_obj)))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def render_html(rows: list, show_time: bool, mode: str) -> str:
    data = json.dumps(rows, default=str)
    cols = [c for c in COLUMNS if show_time or c[0] != "time_s"]
    col_js = json.dumps([{"key": k, "hdr": h, "align": a} for k, h, a in cols])

    # Summary numbers (recomputed in JS for robustness, but also precomputed).
    summary_text = render_summary(rows).replace("\n", "\\n")

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OGC2026 Board</title>
<style>
  :root { color-scheme: dark; }
  body { background:#0e1116; color:#d7dde5; font:14px/1.5 ui-monospace,
         Consolas,Menlo,monospace; margin:0; padding:24px; }
  h1 { font-size:18px; font-weight:600; margin:0 0 4px; color:#e8edf3; }
  .sub { color:#8b97a7; margin:0 0 18px; font-size:12px; }
  table { border-collapse:collapse; width:100%; max-width:1100px; }
  th, td { padding:6px 12px; border-bottom:1px solid #222a35; white-space:nowrap; }
  th { text-align:right; color:#9fb0c3; font-weight:600; cursor:pointer;
       user-select:none; position:sticky; top:0; background:#0e1116; }
  th.left, td.left { text-align:left; }
  td.right, th.right { text-align:right; }
  tr:hover td { background:#161c25; }
  td.bad { color:#ff6b6b; }
  td.good { color:#5ad27e; }
  td.dim { color:#5a6677; }
  .summary { margin-top:22px; background:#141a22; border:1px solid #222a35;
             border-radius:8px; padding:14px 18px; max-width:1100px;
             white-space:pre-wrap; color:#c2ccd9; }
  .summary b { color:#e8edf3; }
</style>
</head>
<body>
<h1>OGC2026 Progress Board</h1>
<p class="sub">mode: __MODE__ &middot; instances: __N__ &middot; generated client-side from embedded data</p>
<table id="t"><thead><tr id="hr"></tr></thead><tbody id="tb"></tbody></table>
<div class="summary" id="sm"></div>
<script>
const ROWS = __DATA__;
const COLS = __COLS__;
const SUMMARY = "__SUMMARY__";

function fmt(v){
  if (v === null || v === undefined) return "-";
  if (typeof v === "boolean") return v ? "Y" : "N";
  if (typeof v === "number"){
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(3);
  }
  return String(v);
}

const hr = document.getElementById("hr");
COLS.forEach((c, idx) => {
  const th = document.createElement("th");
  th.textContent = c.hdr;
  th.className = c.align;
  th.onclick = () => sortBy(c.key, idx);
  hr.appendChild(th);
});

let sortKey = null, sortDir = 1;
function sortBy(key, idx){
  if (sortKey === key) sortDir = -sortDir; else { sortKey = key; sortDir = 1; }
  ROWS.sort((a,b) => {
    let x = a[key], y = b[key];
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * sortDir;
    return String(x).localeCompare(String(y)) * sortDir;
  });
  render();
}

function render(){
  const tb = document.getElementById("tb");
  tb.innerHTML = "";
  ROWS.forEach(r => {
    const tr = document.createElement("tr");
    COLS.forEach(c => {
      const td = document.createElement("td");
      td.className = c.align;
      let v = r[c.key];
      if (c.key === "feasible"){
        td.textContent = (v === null || v === undefined) ? "-" : (v ? "Y" : "N");
        if (v === false) td.classList.add("bad");
        else if (v === true) td.classList.add("good");
      } else {
        td.textContent = fmt(v);
        if (c.key === "obj1" && typeof v === "number" && v > 0) td.classList.add("bad");
        if ((v === null || v === undefined)) td.classList.add("dim");
      }
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
}

document.getElementById("sm").textContent = SUMMARY;
render();
</script>
</body>
</html>
""".replace("__DATA__", data).replace("__COLS__", col_js) \
   .replace("__SUMMARY__", summary_text) \
   .replace("__MODE__", mode) \
   .replace("__N__", str(len(rows)))


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="OGC2026 progress dashboard.")
    ap.add_argument("--sols", default="results",
                    help="Directory of cached solution JSONs (cached mode).")
    ap.add_argument("--run", action="store_true",
                    help="Run the solver fresh per instance (RUN mode).")
    ap.add_argument("--timelimit", type=float, default=60.0,
                    help="Per-instance solver time limit (RUN mode).")
    ap.add_argument("--instances", default=None,
                    help="Comma-separated subset, e.g. prob_11,prob_13.")
    ap.add_argument("--conc", type=int, default=1,
                    help="Max concurrent solver subprocesses (RUN mode).")
    ap.add_argument("--json", default=None, help="Write structured results here.")
    ap.add_argument("--html", default=None, help="Write a dashboard HTML here.")
    args = ap.parse_args()

    if args.instances:
        names = [s.strip() for s in args.instances.split(",") if s.strip()]
    else:
        names = A.list_train_instances()

    show_time = bool(args.run)
    rows: list = [None] * len(names)

    if args.run:
        if args.conc <= 1:
            for i, name in enumerate(names):
                print("[run] {0} (timelimit={1}s) ...".format(name,
                      args.timelimit))
                rows[i] = eval_run(name, args.timelimit)
        else:
            with cf.ThreadPoolExecutor(max_workers=args.conc) as ex:
                futs = {ex.submit(eval_run, name, args.timelimit): i
                        for i, name in enumerate(names)}
                for fut in cf.as_completed(futs):
                    i = futs[fut]
                    rows[i] = fut.result()
                    print("[run] {0} done".format(names[i]))
    else:
        for i, name in enumerate(names):
            rows[i] = eval_cached(name, args.sols)

    rows = [r for r in rows if r is not None]

    table = render_table(rows, show_time)
    summary = render_summary(rows)
    print()
    print(table)
    print()
    print(summary)

    mode = "run" if args.run else "cached"
    if args.json:
        out = {"mode": mode, "timelimit": args.timelimit if args.run else None,
               "rows": rows}
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(out, indent=2, default=str),
                                   encoding="utf-8")
        print("\n[json] wrote {0}".format(args.json))

    if args.html:
        html = render_html(rows, show_time, mode)
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(html, encoding="utf-8")
        print("[html] wrote {0}".format(args.html))

    return 0


if __name__ == "__main__":
    sys.exit(main())
