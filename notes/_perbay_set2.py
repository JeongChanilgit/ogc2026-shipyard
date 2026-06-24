#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OGC2026 per-bay SINGLE-LEG marginal-effect harness  (2026-06-16).

The per-bay engine (perbay.improve, called inside myalgorithm.algorithm() when
OGC_PERBAY=1) ONLY changes per-bay tardiness z1 -- bay assignment is fixed, so
z2/z3 are invariant.  Therefore perbay's EXACT objective contribution in a run is

    marginal_gain = w1 * (z1_before - z1_after)

read from the engine's OWN telemetry (OGC_PERBAY_LOG JSON-lines) -- noise-free,
within the SAME run, independent of how budget was split.  We do NOT re-run the
baseline; we reconstruct the pre-perbay objective as

    pre_obj = final_obj + marginal_gain

This is SINGLE-LEG: one solver call per instance.  The baseline's scores already
exist (notes/research/baselines/tl120_all40_fixed.json, box-OFF -> set2=4.24B, a
LOOSE reference only) and are shown for context, but the authoritative perbay
number is the within-run marginal above.

Run with the env python directly (NOT `conda run` -- crashes w/ 4 CP-SAT workers):
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe notes/_perbay_set2.py \
        --instances SET2 --timelimit 120 --tag set2run

CLI:
  --instances  comma list (prob_29,prob_30) or SET1|SET2|ALL40            [SET2]
  --timelimit  float seconds per instance                                 [120]
  --out        output basename (no extension)                    [notes/perbay-set2]
  --tag        free label recorded in header (no time() needed)

Outputs:  <out>.json  and  <out>.html
"""
import argparse
import datetime
import html as _htmlmod
import json
import os
import sys
import tempfile
import time
import traceback

# --- paths --------------------------------------------------------------------
# This script lives in notes/; project root is its parent.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_INSTANCE_DIR = os.path.join(_ROOT, "instances", "train")
_COMPETITOR_PATH = os.path.join(_ROOT, "notes", "competitor-2026-06-15.json")
_BASELINE_PATH = os.path.join(
    _ROOT, "notes", "research", "baselines", "tl120_all40_fixed.json")


# --- instance selection -------------------------------------------------------
def parse_instances(spec):
    """Return an ordered list of instance names like ['prob_21', ...]."""
    spec = (spec or "SET2").strip()
    up = spec.upper()
    if up == "SET1":
        return [f"prob_{i}" for i in range(1, 21)]
    if up == "SET2":
        return [f"prob_{i}" for i in range(21, 41)]
    if up == "ALL40":
        return [f"prob_{i}" for i in range(1, 41)]
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.isdigit():
            tok = f"prob_{tok}"
        out.append(tok)
    return out


def load_instance(name):
    """Load a fresh prob_info dict (fresh each call to avoid mutation)."""
    path = os.path.join(_INSTANCE_DIR, f"{name}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def instance_meta(prob):
    blocks = prob.get("blocks", [])
    bays = prob.get("bays", [])
    weights = prob.get("weights", {}) or {}
    return {
        "n_blocks": len(blocks),
        "n_bays": len(bays),
        "w1": weights.get("w1", 1.0),
        "w2": weights.get("w2", 1.0),
        "w3": weights.get("w3", 1.0),
    }


# --- reference data -----------------------------------------------------------
def load_competitor():
    """Return {instance_name: competitor_obj_float} or {} if unavailable."""
    try:
        with open(_COMPETITOR_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    comp = data.get("competitor", {}) if isinstance(data, dict) else {}
    out = {}
    for name, rec in comp.items():
        if isinstance(rec, dict) and rec.get("obj") is not None:
            out[name] = rec.get("obj")
    return out


def load_baseline():
    """Return {instance_name: baseline_obj_float} or {} if unavailable.

    LOOSE reference only (box-OFF run, set2=4.24B) -- shown for context, never
    used for the marginal computation."""
    try:
        with open(_BASELINE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    out = {}
    if isinstance(data, dict):
        for name, rec in data.items():
            if isinstance(rec, dict) and rec.get("obj") is not None:
                out[name] = rec.get("obj")
    return out


# --- one single leg -----------------------------------------------------------
def run_instance(algorithm, check_feasibility, name, timelimit):
    """Run ONE perbay solve in-process.  Returns (result_dict, telemetry_list).

    result_dict keys: obj, obj1, obj2, obj3, feasible, wall, status, err.
    telemetry_list: parsed JSON-lines from OGC_PERBAY_LOG (may be 0, 1, or many).
    """
    # Fresh prob_info -- algorithm() may mutate the dict it is given.
    prob = load_instance(name)

    # perbay ON, do NOT carve legacy budget (OGC_PERBAY_S left unset),
    # MAXN default 120 unless the caller already set it.
    os.environ["OGC_PERBAY"] = "1"
    os.environ.setdefault("OGC_PERBAY_MAXN", "120")

    # Fresh temp telemetry path per instance; delete any stale file first.
    fd, log_path = tempfile.mkstemp(prefix=f"perbaylog_{name}_", suffix=".jsonl")
    os.close(fd)
    try:
        # perbay APPENDS, so guarantee emptiness even though mkstemp is empty.
        open(log_path, "w", encoding="utf-8").close()
    except Exception:
        pass
    os.environ["OGC_PERBAY_LOG"] = log_path

    res = {
        "obj": None, "obj1": None, "obj2": None, "obj3": None,
        "feasible": None, "wall": None, "status": "OK", "err": None,
    }
    t0 = time.monotonic()
    try:
        sol = algorithm(prob, float(timelimit))
        res["wall"] = time.monotonic() - t0
        # Re-load a pristine prob_info for the feasibility check (algorithm may
        # have mutated the one it was given).
        prob_check = load_instance(name)
        fc = check_feasibility(prob_check, sol)
        res["feasible"] = bool(fc.get("feasible"))
        res["obj"] = fc.get("objective")
        res["obj1"] = fc.get("obj1")
        res["obj2"] = fc.get("obj2")
        res["obj3"] = fc.get("obj3")
        if not res["feasible"]:
            res["status"] = "INFEASIBLE"
            res["stage"] = fc.get("stage")
            viol = fc.get("violations") or []
            res["violations"] = viol[:5]
    except Exception as e:
        res["wall"] = time.monotonic() - t0
        res["status"] = "CRASH"
        res["err"] = f"{type(e).__name__}: {e}"
        res["traceback"] = traceback.format_exc().splitlines()[-6:]

    # Parse telemetry (defensively: 0, 1, or several lines).
    telemetry = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    telemetry.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    try:
        os.remove(log_path)
    except Exception:
        pass

    return res, telemetry


# --- telemetry aggregation ----------------------------------------------------
def summarize_telemetry(telemetry):
    """Aggregate across ALL improve() JSON lines for this instance.

    Returns a dict with the within-run marginal pieces plus a flat list of ALL
    bay records (with status) for the detail view."""
    fired_any = False
    total_dz1 = 0.0                # sum over FIRED lines of (z1_before-z1_after)
    n_bays_improved = 0
    n_bays_skipped_maxn = 0
    bay_records = []              # ALL bays (every status) flattened
    sum_wall = 0.0
    n_calls = len(telemetry)
    # For display: first z1_before / last z1_after across the run.
    z1_before_disp = None
    z1_after_disp = None

    for rec in telemetry:
        fired = bool(rec.get("fired"))
        if fired:
            fired_any = True
            zb = rec.get("z1_before")
            za = rec.get("z1_after")
            if zb is not None and za is not None:
                total_dz1 += (float(zb) - float(za))
        sum_wall += float(rec.get("total_wall") or 0.0)
        # display values: capture first non-None before, last non-None after
        if rec.get("z1_before") is not None and z1_before_disp is None:
            z1_before_disp = float(rec.get("z1_before"))
        if rec.get("z1_after") is not None:
            z1_after_disp = float(rec.get("z1_after"))
        for b in rec.get("bays", []):
            status = b.get("status")
            if status == "improved":
                n_bays_improved += 1
            elif status == "skipped_maxn":
                n_bays_skipped_maxn += 1
            bay_records.append({
                "bay": b.get("bay"),
                "n_blocks": b.get("n_blocks"),
                "cur_tard": b.get("cur_tard"),
                "new_tard": b.get("new_tard"),
                "wall": b.get("wall"),
                "status": status,
                "err": b.get("err"),
            })

    return {
        "n_calls": n_calls,
        "fired": fired_any,
        "total_dz1": total_dz1,
        "n_bays_improved": n_bays_improved,
        "n_bays_skipped_maxn": n_bays_skipped_maxn,
        "sum_bay_wall": sum_wall,
        "z1_before": z1_before_disp,
        "z1_after": z1_after_disp,
        "bay_records": bay_records,
    }


# --- HTML helpers -------------------------------------------------------------
def _fmt(x, nd=2):
    if x is None:
        return "&mdash;"
    try:
        if isinstance(x, float):
            return f"{x:,.{nd}f}"
        return f"{x:,}"
    except Exception:
        return _htmlmod.escape(str(x))


def _fmt0(x):
    if x is None:
        return "&mdash;"
    try:
        return f"{x:,.0f}"
    except Exception:
        return _htmlmod.escape(str(x))


# --- HTML rendering -----------------------------------------------------------
def render_html(records, totals, cfg):
    esc = _htmlmod.escape
    rows = []
    detail_sections = []

    for r in records:
        feas = r.get("feasible")
        fired = r.get("fired")
        gain = r.get("marginal_gain")
        # row color
        if feas is False:
            cls = "bad"
        elif fired and gain is not None and gain > 0:
            cls = "good"
        else:
            cls = "neu"

        status = r.get("status")
        final_cell = (_fmt0(r.get("final_obj")) if feas
                      else f"<b>{esc(str(status))}</b>")
        feas_cell = ("yes" if feas else "<b>NO (-1)</b>")
        fired_cell = "yes" if fired else "no"
        z1_arrow = "{zb}&rarr;{za}".format(
            zb=_fmt0(r.get("z1_before")), za=_fmt0(r.get("z1_after")))
        mpct = r.get("marginal_pct")
        mpct_s = f"{mpct*100:.2f}%" if mpct is not None else "&mdash;"

        rows.append(
            "<tr class='{cls}'>"
            "<td class='inst'>{inst}</td>"
            "<td class='num'>{nb}</td>"
            "<td class='num'>{nbay}</td>"
            "<td class='num'>{w1}</td>"
            "<td class='num'>{fired}</td>"
            "<td class='num'>{baysimp}</td>"
            "<td class='num small'>{z1}</td>"
            "<td class='num'>{dz1}</td>"
            "<td class='num good'>{gain}</td>"
            "<td class='num'>{mpct}</td>"
            "<td class='num'>{final}</td>"
            "<td class='num {feascls}'>{feas}</td>"
            "<td class='num'>{wall}</td>"
            "<td class='num'>{comp}</td>"
            "</tr>".format(
                cls=cls, inst=esc(r["instance"]),
                nb=r["n_blocks"], nbay=r["n_bays"], w1=_fmt0(r.get("w1")),
                fired=fired_cell, baysimp=r.get("n_bays_improved", 0),
                z1=z1_arrow, dz1=_fmt0(r.get("dz1")),
                gain=(f"-{gain:,.0f}" if (gain and gain > 0) else "0"),
                mpct=mpct_s, final=final_cell,
                feascls=("bad" if feas is False else "good"), feas=feas_cell,
                wall=_fmt(r.get("wall"), 1), comp=_fmt0(r.get("competitor_obj")),
            )
        )

        # detail: ALL bay records (every status)
        bays = r.get("bay_records", [])
        if bays or r.get("n_calls"):
            brows = []
            for b in bays:
                ct = b.get("cur_tard")
                nt = b.get("new_tard")
                drop = (ct - nt) if (ct is not None and nt is not None) else None
                st = b.get("status")
                st_cls = ("good" if st == "improved"
                          else ("bad" if st == "error" else "neu"))
                brows.append(
                    "<tr><td class='num'>{bay}</td><td class='num'>{n}</td>"
                    "<td class='num'>{ct}</td><td class='num'>{nt}</td>"
                    "<td class='num good'>{drop}</td><td class='num'>{wall}</td>"
                    "<td class='{stcls}'>{st}</td></tr>".format(
                        bay=_fmt0(b.get("bay")), n=_fmt0(b.get("n_blocks")),
                        ct=_fmt0(ct), nt=(_fmt0(nt) if nt is not None else "&mdash;"),
                        drop=(f"-{drop:,.0f}" if drop else "0"),
                        wall=_fmt(b.get("wall"), 2),
                        stcls=st_cls, st=esc(str(st)),
                    )
                )
            if not brows:
                inner = ("<p class='muted'>perbay ran {n} improve() call(s); "
                         "no work-bays recorded.</p>".format(n=r.get("n_calls", 0)))
            else:
                inner = (
                    "<table class='detail'><thead><tr>"
                    "<th>bay</th><th>n_blocks</th><th>cur_tard</th><th>new_tard</th>"
                    "<th>&Delta;tard</th><th>wall(s)</th><th>status</th>"
                    "</tr></thead><tbody>" + "".join(brows) + "</tbody></table>"
                )
            summary_line = (
                "calls={c}, fired={f}, bays improved={i}, skipped_maxn={sm}, "
                "z1 {zb}&rarr;{za}, &Delta;z1={dz1}, gain=-{g}, "
                "bay-wall&Sigma;={w}s".format(
                    c=r.get("n_calls", 0),
                    f=("yes" if r.get("fired") else "no"),
                    i=r.get("n_bays_improved", 0),
                    sm=r.get("n_bays_skipped_maxn", 0),
                    zb=_fmt0(r.get("z1_before")), za=_fmt0(r.get("z1_after")),
                    dz1=_fmt0(r.get("dz1")),
                    g=(f"{r.get('marginal_gain'):,.0f}" if r.get("marginal_gain") else "0"),
                    w=_fmt(r.get("sum_bay_wall"), 1),
                )
            )
            detail_sections.append(
                "<details><summary><b>{inst}</b> &mdash; {sl}</summary>{inner}</details>".format(
                    inst=esc(r["instance"]), sl=summary_line, inner=inner)
            )

    findings = build_findings(records, totals)
    findings_html = "<ul>" + "".join(f"<li>{esc(f)}</li>" for f in findings) + "</ul>"

    t = totals
    n = len(records)
    feas_n = t.get("n_feasible", 0)
    feas_ok = (feas_n == n and n > 0)
    over_tl = (t.get("max_wall") or 0) > cfg["timelimit"] + 1.0

    cfg_line = "instances={i} (n={n}) &middot; TL={tl}s &middot; tag={tag} &middot; generated={dt}".format(
        i=esc(cfg["instances_spec"]), n=n, tl=cfg["timelimit"],
        tag=esc(cfg.get("tag") or "&mdash;"), dt=esc(cfg["generated"]))

    head = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OGC2026 per-bay single-leg (set2)</title>
<style>
 :root{--good:#1a7f37;--bad:#b91c1c;--neu:#6b7280;}
 *{box-sizing:border-box;}
 body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;
      background:#f1f5f9;color:#0f172a;font-size:13px;line-height:1.4;}
 header{background:#0f172a;color:#e2e8f0;padding:18px 24px;}
 header h1{margin:0 0 4px;font-size:20px;}
 header .cfg{color:#94a3b8;font-size:12px;}
 .wrap{padding:20px 24px;max-width:1500px;margin:0 auto;}
 .cards{display:flex;flex-wrap:wrap;gap:14px;margin:0 0 22px;}
 .card{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:14px 18px;
       min-width:200px;box-shadow:0 1px 2px rgba(0,0,0,.04);}
 .card h3{margin:0 0 8px;font-size:13px;color:#475569;text-transform:uppercase;letter-spacing:.04em;}
 .card .big{font-size:22px;font-weight:700;}
 .card p{margin:3px 0;}
 .card.alarm{border-color:var(--bad);}
 .card.alarm .big{color:var(--bad);}
 table{border-collapse:collapse;width:100%;background:#fff;font-size:12px;
       box-shadow:0 1px 3px rgba(0,0,0,.06);border-radius:6px;overflow:hidden;}
 th,td{padding:5px 8px;border-bottom:1px solid #eef2f7;text-align:left;}
 th{background:#1e293b;color:#e2e8f0;font-weight:600;cursor:pointer;
    position:sticky;top:0;white-space:nowrap;}
 td.num{text-align:right;font-variant-numeric:tabular-nums;}
 td.small{font-size:11px;color:#475569;}
 td.inst{font-weight:600;}
 tr.good td{background:#f0fdf4;}
 tr.bad td{background:#fef2f2;}
 tr.neu td{background:#fff;}
 .good{color:var(--good);} .bad{color:var(--bad);font-weight:700;} .muted,.neu{color:var(--neu);}
 h2{margin:26px 0 10px;font-size:16px;border-bottom:2px solid #cbd5e1;padding-bottom:5px;}
 details{background:#fff;border:1px solid #e2e8f0;border-radius:6px;margin:6px 0;padding:6px 12px;}
 summary{cursor:pointer;font-size:12px;}
 table.detail{margin:8px 0;width:auto;min-width:520px;}
 .findings{background:#fff;border-left:4px solid #2563eb;padding:12px 18px;border-radius:0 6px 6px 0;}
 .findings li{margin:4px 0;}
 .note{color:#64748b;font-size:11px;margin:8px 0 0;}
</style></head><body>
<header><h1>OGC2026 per-bay SINGLE-LEG marginal &mdash; set2</h1>
<div class="cfg">""" + cfg_line + "</div></header><div class='wrap'>"

    cards = (
        "<div class='cards'>"
        "<div class='card'><h3>perbay marginal gain (clean)</h3>"
        "<p class='big good'>-{mg}</p>"
        "<p class='muted'>&Sigma; w1&middot;&Delta;z1 within-run, noise-free</p></div>"
        "<div class='card'><h3>Fire rate</h3>"
        "<p class='big'>{fired}/{n}</p>"
        "<p class='muted'>improve() fired on at least one bay</p></div>"
        "<div class='card {fcls}'><h3>Feasibility (set2 safety)</h3>"
        "<p class='big'>{feas}/{n}</p>"
        "<p class='muted'>{fmsg}</p></div>"
        "<div class='card {wcls}'><h3>Max wall</h3>"
        "<p class='big'>{mw}s</p><p class='muted'>TL={tl}s ({ok})</p></div>"
        "<div class='card'><h3>&Sigma; final obj (feasible)</h3>"
        "<p class='big'>{fo}</p>"
        "<p class='muted'>pre-perbay &Sigma;: {po}</p>"
        "<p class='muted'>competitor &Sigma;: {co}</p></div>"
        "</div>".format(
            mg=_fmt0(t.get("sum_marginal_gain")),
            fired=t.get("n_fired", 0), n=n,
            fcls=("alarm" if not feas_ok else ""),
            feas=feas_n, fmsg=("ALL feasible" if feas_ok else "INFEASIBLE present = -1!"),
            wcls=("alarm" if over_tl else ""),
            mw=_fmt(t.get("max_wall"), 1), tl=cfg["timelimit"],
            ok=("OK &le; TL" if not over_tl else "OVER TL!"),
            fo=_fmt0(t.get("sum_final_obj")), po=_fmt0(t.get("sum_pre_obj")),
            co=_fmt0(t.get("sum_competitor_obj")),
        )
    )

    findings_block = ("<h2>Findings (auto-generated)</h2><div class='findings'>"
                      + findings_html + "</div>")

    table = (
        "<h2>Per-instance</h2>"
        "<table id='tbl'><thead><tr>"
        "<th onclick='sortT(0)'>instance</th><th onclick='sortT(1)'>n_blk</th>"
        "<th onclick='sortT(2)'>n_bay</th><th onclick='sortT(3)'>w1</th>"
        "<th>fired?</th><th onclick='sortT(5)'>bays&uarr;</th>"
        "<th>z1 before&rarr;after</th><th onclick='sortT(7)'>&Delta;z1</th>"
        "<th onclick='sortT(8)'>marginal gain</th><th onclick='sortT(9)'>marginal %</th>"
        "<th onclick='sortT(10)'>final obj</th><th>feas</th>"
        "<th onclick='sortT(12)'>wall</th><th onclick='sortT(13)'>comp obj</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        "<p class='note'>marginal gain = w1&middot;(z1_before&minus;z1_after) read from "
        "perbay telemetry (noise-free, within the SAME run). pre_obj = final_obj + "
        "marginal_gain. Baseline reference (tl120_all40_fixed.json) is box-OFF "
        "(set2=4.24B) and LOOSE; the authoritative perbay number is this within-run "
        "marginal.</p>"
    )

    details = (
        "<h2>Per-bay detail (where perbay engaged vs skipped)</h2>"
        + "".join(detail_sections)
        if detail_sections else
        "<h2>Per-bay detail</h2><p class='muted'>No perbay telemetry recorded.</p>"
    )

    js = """
<script>
function sortT(c){
 var t=document.getElementById('tbl'),b=t.tBodies[0],r=[].slice.call(b.rows);
 var asc=t.getAttribute('data-c')==c&&t.getAttribute('data-a')!='1';
 t.setAttribute('data-c',c);t.setAttribute('data-a',asc?'1':'0');
 r.sort(function(x,y){
  var a=x.cells[c].innerText.replace(/[,%\\s]/g,''),d=y.cells[c].innerText.replace(/[,%\\s]/g,'');
  var na=parseFloat(a),nb=parseFloat(d);
  if(!isNaN(na)&&!isNaN(nb))return asc?na-nb:nb-na;
  return asc?a.localeCompare(d):d.localeCompare(a);
 });
 r.forEach(function(x){b.appendChild(x);});
}
</script>"""

    return head + cards + findings_block + table + details + js + "</div></body></html>"


def build_findings(records, totals):
    out = []
    t = totals
    n = len(records)

    out.append(
        "Total perbay marginal gain (clean within-run): "
        "{mg:,.0f} = sum of w1*(z1_before - z1_after) over all fired runs.".format(
            mg=(t.get("sum_marginal_gain") or 0.0)))

    out.append(
        "perbay fire-rate: {f}/{n} instances had improve() fire "
        "(at least one work-bay solved).".format(f=t.get("n_fired", 0), n=n))

    # top-3 by marginal gain
    gainful = [(r["instance"], r.get("marginal_gain") or 0.0) for r in records
               if (r.get("marginal_gain") or 0.0) > 0]
    gainful.sort(key=lambda x: x[1], reverse=True)
    if gainful:
        top = ", ".join(f"{nm} (-{g:,.0f})" for nm, g in gainful[:3])
        out.append(f"perbay helped most on: {top}.")
    else:
        out.append("perbay produced no objective reduction on any instance "
                   "(no fired run lowered z1).")

    # skipped_maxn signal
    sk = t.get("n_bays_skipped_maxn", 0)
    if sk:
        skinst = sorted({r["instance"] for r in records
                         if r.get("n_bays_skipped_maxn", 0) > 0})
        out.append(
            "{sk} bay(s) were skipped_maxn (too large for pairwise CP-SAT) across "
            "{ni} instance(s): {il}. These signal a MAXN tuning lever -- raising "
            "OGC_PERBAY_MAXN may engage them (watch wall).".format(
                sk=sk, ni=len(skinst), il=", ".join(skinst)))
    else:
        out.append("No bays were skipped_maxn (MAXN large enough for every "
                   "tardy bay).")

    # infeasible (-1) -- critical set2 safety
    infeas = [r["instance"] for r in records if r.get("feasible") is False]
    if infeas:
        out.append("CRITICAL: INFEASIBLE / -1 instances: {il} -- each costs ~ -R/2 "
                   "in scoring. set2 is the -1 frontier; this MUST be 0.".format(
                       il=", ".join(infeas)))
    else:
        out.append("No infeasible instances: every set2 solve was feasible "
                   "(never -1).")

    if t.get("max_wall") is not None:
        out.append("Max wall over all runs: {mw:.1f}s (TL was {tl}s).".format(
            mw=t["max_wall"], tl=t.get("timelimit")))

    # vs competitor (context, set2 per-instance)
    if t.get("sum_final_obj") is not None and t.get("sum_competitor_obj") is not None:
        out.append(
            "Context: our &Sigma; final obj over feasible w/ competitor data = "
            "{fo:,.0f} vs competitor &Sigma; = {co:,.0f}.".format(
                fo=t["sum_final_obj_with_comp"], co=t["sum_competitor_obj"]))
    return out


# --- totals -------------------------------------------------------------------
def compute_totals(records, instances_spec, timelimit):
    sum_marginal = 0.0
    n_fired = 0
    n_feasible = 0
    n_bays_improved = 0
    n_bays_skipped_maxn = 0
    max_wall = 0.0
    sum_final = 0.0
    sum_pre = 0.0
    sum_comp = 0.0
    sum_final_with_comp = 0.0
    for r in records:
        if r.get("wall") is not None:
            max_wall = max(max_wall, r["wall"])
        if r.get("fired"):
            n_fired += 1
        if r.get("feasible"):
            n_feasible += 1
        n_bays_improved += r.get("n_bays_improved", 0)
        n_bays_skipped_maxn += r.get("n_bays_skipped_maxn", 0)
        g = r.get("marginal_gain") or 0.0
        if g > 0:
            sum_marginal += g
        if r.get("feasible") and r.get("final_obj") is not None:
            sum_final += r["final_obj"]
            if r.get("pre_obj") is not None:
                sum_pre += r["pre_obj"]
            if r.get("competitor_obj") is not None:
                sum_final_with_comp += r["final_obj"]
        if r.get("competitor_obj") is not None:
            sum_comp += r["competitor_obj"]

    n = len(records)
    return {
        "instances_spec": instances_spec,
        "timelimit": timelimit,
        "n_instances": n,
        "sum_marginal_gain": sum_marginal,
        "n_fired": n_fired,
        "n_feasible": n_feasible,
        "n_bays_improved": n_bays_improved,
        "n_bays_skipped_maxn": n_bays_skipped_maxn,
        "max_wall": (max_wall if records else None),
        "sum_final_obj": (sum_final if n_feasible else None),
        "sum_pre_obj": (sum_pre if n_feasible else None),
        "sum_competitor_obj": (sum_comp if sum_comp else None),
        "sum_final_obj_with_comp": (sum_final_with_comp if sum_final_with_comp else None),
    }


# --- main ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="OGC2026 per-bay single-leg marginal harness (set2)")
    ap.add_argument("--instances", default="SET2",
                    help="comma list (prob_29,prob_30) or SET1|SET2|ALL40")
    ap.add_argument("--timelimit", type=float, default=120.0)
    ap.add_argument("--out", default=os.path.join("notes", "perbay-set2"),
                    help="output basename (no extension)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    names = parse_instances(args.instances)
    if not names:
        print("No instances selected.", file=sys.stderr)
        sys.exit(2)

    # Resolve --out relative to project root.
    out_base = args.out
    if not os.path.isabs(out_base):
        out_base = os.path.join(_ROOT, out_base)
    out_dir = os.path.dirname(out_base)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = {
        "instances_spec": args.instances,
        "timelimit": args.timelimit,
        "tag": args.tag,
        "generated": generated,
    }

    print(f"[perbay-set2] importing solver from {_SRC}", flush=True)
    import myalgorithm
    from utils import check_feasibility
    algorithm = myalgorithm.algorithm

    competitor = load_competitor()
    baseline = load_baseline()
    print(f"[perbay-set2] competitor entries: {len(competitor)}, "
          f"baseline entries: {len(baseline)}", flush=True)
    # Confirm legacy budget is NOT carved.
    print(f"[perbay-set2] OGC_PERBAY_S={os.environ.get('OGC_PERBAY_S', '<unset>')} "
          f"(must be unset/0 -- legacy budget NOT carved)", flush=True)

    records = []
    for idx, name in enumerate(names, 1):
        print(f"[perbay-set2] ({idx}/{len(names)}) {name}: loading meta...", flush=True)
        try:
            meta = instance_meta(load_instance(name))
        except Exception as e:
            print(f"[perbay-set2]   FAILED to load {name}: {e}", flush=True)
            continue

        print(f"[perbay-set2]   {name}: SINGLE-LEG (OGC_PERBAY=1) "
              f"TL={args.timelimit}s...", flush=True)
        res, telemetry = run_instance(algorithm, check_feasibility, name, args.timelimit)
        tel = summarize_telemetry(telemetry)

        w1 = meta["w1"] if meta["w1"] is not None else 1.0
        dz1 = tel["total_dz1"]
        marginal_gain = w1 * dz1
        final_obj = res.get("obj")
        pre_obj = None
        marginal_pct = 0.0
        if final_obj is not None:
            pre_obj = final_obj + marginal_gain
            marginal_pct = (marginal_gain / pre_obj) if (pre_obj and pre_obj > 0) else 0.0

        rec = {
            "instance": name,
            "n_blocks": meta["n_blocks"],
            "n_bays": meta["n_bays"],
            "w1": w1, "w2": meta["w2"], "w3": meta["w3"],
            "final_obj": final_obj,
            "final_obj1": res.get("obj1"),
            "final_obj2": res.get("obj2"),
            "final_obj3": res.get("obj3"),
            "feasible": res.get("feasible"),
            "status": res.get("status"),
            "err": res.get("err"),
            "wall": res.get("wall"),
            "fired": tel["fired"],
            "n_bays_improved": tel["n_bays_improved"],
            "n_bays_skipped_maxn": tel["n_bays_skipped_maxn"],
            "z1_before": tel["z1_before"],
            "z1_after": tel["z1_after"],
            "dz1": dz1,
            "marginal_gain": marginal_gain,
            "pre_obj": pre_obj,
            "marginal_pct": marginal_pct,
            "n_calls": tel["n_calls"],
            "sum_bay_wall": tel["sum_bay_wall"],
            "bay_records": tel["bay_records"],
            "telemetry_raw": telemetry,
            "competitor_obj": competitor.get(name),
            "baseline_obj": baseline.get(name),
        }
        records.append(rec)

        # progress line per instance
        feas_s = ("FEAS" if res.get("feasible")
                  else f"!!{res.get('status')}!!")
        wall_s = f"{res['wall']:.1f}s" if res.get("wall") is not None else "?"
        print("[perbay-set2]     {nm}: {fs} obj={ob} fired={fi} bays^={bi} "
              "z1 {zb}->{za} dz1={dz} gain=-{mg:,.0f} wall={ws}".format(
                  nm=name, fs=feas_s,
                  ob=(f"{final_obj:,.0f}" if final_obj is not None else "None"),
                  fi=tel["fired"], bi=tel["n_bays_improved"],
                  zb=_fmt0(tel["z1_before"]).replace("&mdash;", "-"),
                  za=_fmt0(tel["z1_after"]).replace("&mdash;", "-"),
                  dz=f"{dz1:.0f}", mg=marginal_gain, ws=wall_s), flush=True)

    totals = compute_totals(records, args.instances, args.timelimit)

    # --- write JSON ---------------------------------------------------------
    json_path = out_base + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"config": cfg, "totals": totals, "instances": records},
                  f, indent=2, ensure_ascii=False)
    print(f"[perbay-set2] wrote {json_path}", flush=True)

    # --- write HTML ---------------------------------------------------------
    html_path = out_base + ".html"
    html = render_html(records, totals, cfg)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[perbay-set2] wrote {html_path}", flush=True)

    print("[perbay-set2] DONE.", flush=True)
    print(f"[perbay-set2] JSON: {json_path}")
    print(f"[perbay-set2] HTML: {html_path}")
    # totals summary line
    print("[perbay-set2] TOTALS: marginal_gain=-{mg:,.0f} fired={fi}/{n} "
          "feasible={fe}/{n} max_wall={mw} sum_final={sf}".format(
              mg=(totals.get("sum_marginal_gain") or 0.0),
              fi=totals.get("n_fired", 0), n=totals.get("n_instances", 0),
              fe=totals.get("n_feasible", 0),
              mw=(f"{totals['max_wall']:.1f}s" if totals.get("max_wall") else "?"),
              sf=(f"{totals['sum_final_obj']:,.0f}" if totals.get("sum_final_obj") else "?")),
          flush=True)


if __name__ == "__main__":
    main()
