#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OGC2026 pipeline audit harness  (2026-06-16).

Records the WHOLE solve process per instance for analysis:
  * two in-process legs per instance -- BASE (OGC_PERBAY=0) vs PERBAY (OGC_PERBAY=1),
  * wall times (time.monotonic), feasibility + objective breakdown (z1/z2/z3),
  * the per-bay perbay telemetry (JSON-lines emitted by perbay.improve via
    OGC_PERBAY_LOG) parsed back in full,
  * competitor reference (set1) from notes/competitor-2026-06-15.json,
emitting (1) a raw structured <out>.json and (2) a self-contained <out>.html
dashboard.

Run with the env python directly (NOT `conda run` -- crashes w/ 4 CP-SAT workers):
    C:/Users/peter/anaconda3/envs/ogc2025/python.exe notes/_pipeline_audit.py \
        --instances SET1 --timelimit 120 --tag run1

CLI:
  --instances  comma list (prob_13,prob_14) OR keyword SET1|SET2|ALL40   [SET1]
  --timelimit  float seconds per leg                                     [120]
  --out        output basename (no ext)                          [notes/pipeline-audit]
  --tag        free label recorded in header / used in default filename suffix

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
# set1 competitor official total (from competitor file _totals.set1_official)
_COMPETITOR_SET1_TOTAL = 931465.11


# --- instance selection -------------------------------------------------------
def parse_instances(spec):
    """Return an ordered list of instance names like ['prob_3', ...]."""
    spec = (spec or "SET1").strip()
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
    """Load a fresh prob_info dict (fresh each leg to avoid mutation)."""
    path = os.path.join(_INSTANCE_DIR, f"{name}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def instance_meta(prob):
    blocks = prob.get("blocks", [])
    bays = prob.get("bays", [])
    weights = prob.get("weights", {}) or {}
    bay_sizes = []
    for by in bays:
        try:
            bay_sizes.append([int(by.get("width", 0)), int(by.get("height", 0))])
        except Exception:
            bay_sizes.append([by.get("width"), by.get("height")])
    return {
        "n_blocks": len(blocks),
        "n_bays": len(bays),
        "weights": {
            "w1": weights.get("w1"),
            "w2": weights.get("w2"),
            "w3": weights.get("w3"),
        },
        "bay_sizes": bay_sizes,
    }


# --- competitor reference -----------------------------------------------------
def load_competitor():
    """Return {instance_name: {'obj','z1','z2','z3'}} or {} if unavailable."""
    try:
        with open(_COMPETITOR_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    comp = data.get("competitor", {}) if isinstance(data, dict) else {}
    out = {}
    for name, rec in comp.items():
        if not isinstance(rec, dict):
            continue
        out[name] = {
            "obj": rec.get("obj"),
            "z1": rec.get("z1"),
            "z2": rec.get("z2"),
            "z3": rec.get("z3"),
        }
    return out


# --- one leg ------------------------------------------------------------------
def run_leg(algorithm, check_feasibility, name, timelimit, perbay_on):
    """Run a single leg in-process.  Returns (result_dict, telemetry_list).

    result_dict keys: obj, obj1, obj2, obj3, feasible, wall, status, err,
    (stage / violations on infeasible).
    telemetry_list: parsed JSON-lines from OGC_PERBAY_LOG (empty for BASE leg
    or if nothing was emitted).
    """
    # Fresh prob_info -- never reuse across legs (algorithm may mutate).
    prob = load_instance(name)

    log_path = None
    if perbay_on:
        os.environ["OGC_PERBAY"] = "1"
        fd, log_path = tempfile.mkstemp(prefix=f"perbaylog_{name}_", suffix=".jsonl")
        os.close(fd)
        # Start clean: truncate any prior content (mkstemp gives an empty file,
        # but perbay APPENDS, so guarantee emptiness).
        try:
            open(log_path, "w", encoding="utf-8").close()
        except Exception:
            pass
        os.environ["OGC_PERBAY_LOG"] = log_path
    else:
        os.environ["OGC_PERBAY"] = "0"
        os.environ.pop("OGC_PERBAY_LOG", None)

    res = {
        "obj": None, "obj1": None, "obj2": None, "obj3": None,
        "feasible": None, "wall": None, "status": "OK", "err": None,
    }
    t0 = time.monotonic()
    try:
        sol = algorithm(prob, float(timelimit))
        res["wall"] = time.monotonic() - t0
        # Re-load a clean prob_info for the feasibility check (algorithm may have
        # mutated the one it was given; check on a pristine copy).
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

    # Parse telemetry (perbay leg only).
    telemetry = []
    if perbay_on and log_path:
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


# --- telemetry summary --------------------------------------------------------
def summarize_telemetry(telemetry):
    """Collapse the list of improve() JSON records into a summary dict + a flat
    list of improved bays (for the detail table)."""
    fired_any = False
    improved_bays = []          # flat: {bay, n_blocks, cur_tard, new_tard, wall}
    n_bays_seen = 0
    n_bays_improved = 0
    sum_wall = 0.0
    z1_before = None
    z1_after = None
    n_calls = len(telemetry)

    for rec in telemetry:
        if rec.get("fired"):
            fired_any = True
        sum_wall += float(rec.get("total_wall") or 0.0)
        zb = rec.get("z1_before")
        za = rec.get("z1_after")
        if zb is not None:
            z1_before = zb if z1_before is None else min(z1_before, zb)
        # z1_after: take the value from the LAST call that fired, else min.
        if za is not None:
            z1_after = za if z1_after is None else min(z1_after, za)
        for b in rec.get("bays", []):
            n_bays_seen += 1
            status = b.get("status")
            if status == "improved":
                n_bays_improved += 1
                improved_bays.append({
                    "bay": b.get("bay"),
                    "n_blocks": b.get("n_blocks"),
                    "cur_tard": b.get("cur_tard"),
                    "new_tard": b.get("new_tard"),
                    "wall": b.get("wall"),
                })

    return {
        "n_calls": n_calls,
        "fired": fired_any,
        "n_bays_seen": n_bays_seen,
        "n_bays_improved": n_bays_improved,
        "sum_bay_wall": sum_wall,
        "z1_before": z1_before,
        "z1_after": z1_after,
        "improved_bays": improved_bays,
    }


# --- verdict ------------------------------------------------------------------
def compute_verdict(base, perbay):
    """Return (verdict, delta_obj, delta_pct, delta_z1)."""
    bo, po = base.get("obj"), perbay.get("obj")
    bf, pf = base.get("feasible"), perbay.get("feasible")
    # Infeasibility / crash dominates.
    if pf is False or perbay.get("status") in ("CRASH", "INFEASIBLE"):
        return "regression", None, None, None
    if bf is False or base.get("status") in ("CRASH", "INFEASIBLE"):
        # perbay feasible, base not -> perbay clearly better
        return "perbay", None, None, None
    if bo is None or po is None:
        return "tie", None, None, None
    d = po - bo
    dpct = (d / bo * 100.0) if bo else 0.0
    dz1 = None
    if base.get("obj1") is not None and perbay.get("obj1") is not None:
        dz1 = perbay["obj1"] - base["obj1"]
    # tolerance for floating noise
    if abs(d) < 1e-6:
        return "tie", d, dpct, dz1
    if d < 0:
        return "perbay", d, dpct, dz1
    return "regression", d, dpct, dz1


# --- HTML rendering -----------------------------------------------------------
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


def render_html(records, totals, cfg):
    esc = _htmlmod.escape
    rows = []
    detail_sections = []

    for r in records:
        base = r["base"]
        pb = r["perbay"]
        tel = r["_tel_summary"]
        verdict = r["winner"]
        # row color
        if verdict == "perbay":
            cls = "good"
        elif verdict == "regression":
            cls = "bad"
        else:
            cls = "neu"
        if base.get("status") in ("CRASH", "INFEASIBLE") or \
           pb.get("status") in ("CRASH", "INFEASIBLE"):
            cls = "bad"

        w = r["weights"]
        comp = r.get("competitor_obj")
        base_brk = f"{_fmt0(base.get('obj1'))} / {_fmt0(base.get('obj2'))} / {_fmt0(base.get('obj3'))}"
        pb_brk = f"{_fmt0(pb.get('obj1'))} / {_fmt0(pb.get('obj2'))} / {_fmt0(pb.get('obj3'))}"
        fired = "yes" if tel.get("fired") else "no"
        bays_imp = tel.get("n_bays_improved", 0)
        dpct = r.get("delta_pct")
        dpct_s = f"{dpct:+.2f}%" if dpct is not None else "&mdash;"
        dobj = r.get("delta_obj")
        dobj_s = f"{dobj:+,.1f}" if dobj is not None else "&mdash;"

        base_status = base.get("status")
        pb_status = pb.get("status")
        base_obj_cell = _fmt0(base.get("obj")) if base.get("feasible") else f"<b>{esc(str(base_status))}</b>"
        pb_obj_cell = _fmt0(pb.get("obj")) if pb.get("feasible") else f"<b>{esc(str(pb_status))}</b>"

        rows.append(
            "<tr class='{cls}'>"
            "<td class='inst'>{inst}</td>"
            "<td class='num'>{nb}</td>"
            "<td class='num'>{nbay}</td>"
            "<td class='num small'>{w1}/{w2}/{w3}</td>"
            "<td class='num'>{base_obj}</td>"
            "<td class='num small'>{base_brk}</td>"
            "<td class='num'>{pb_obj}</td>"
            "<td class='num small'>{pb_brk}</td>"
            "<td class='num'>{dobj}</td>"
            "<td class='num'>{dpct}</td>"
            "<td class='num'>{bw}</td>"
            "<td class='num'>{pw}</td>"
            "<td class='num'>{fired}</td>"
            "<td class='num'>{bays_imp}</td>"
            "<td class='num'>{comp}</td>"
            "<td class='verdict {cls}'>{verdict}</td>"
            "</tr>".format(
                cls=cls, inst=esc(r["instance"]), nb=r["n_blocks"], nbay=r["n_bays"],
                w1=_fmt0(w.get("w1")), w2=_fmt0(w.get("w2")), w3=_fmt0(w.get("w3")),
                base_obj=base_obj_cell, base_brk=base_brk,
                pb_obj=pb_obj_cell, pb_brk=pb_brk,
                dobj=dobj_s, dpct=dpct_s,
                bw=_fmt(base.get("wall"), 1), pw=_fmt(pb.get("wall"), 1),
                fired=fired, bays_imp=bays_imp, comp=_fmt0(comp),
                verdict=esc(verdict),
            )
        )

        # detail: improved bays
        imp = tel.get("improved_bays", [])
        if imp or tel.get("n_calls"):
            brows = []
            for b in imp:
                ct = b.get("cur_tard")
                nt = b.get("new_tard")
                drop = (ct - nt) if (ct is not None and nt is not None) else None
                brows.append(
                    "<tr><td class='num'>{bay}</td><td class='num'>{n}</td>"
                    "<td class='num'>{ct}</td><td class='num'>{nt}</td>"
                    "<td class='num good'>{drop}</td><td class='num'>{wall}</td></tr>".format(
                        bay=_fmt0(b.get("bay")), n=_fmt0(b.get("n_blocks")),
                        ct=_fmt0(ct), nt=_fmt0(nt),
                        drop=(f"-{drop:,.0f}" if drop else "0"),
                        wall=_fmt(b.get("wall"), 2),
                    )
                )
            if not brows:
                inner = "<p class='muted'>perbay ran {n} improve() call(s); no bay improved.</p>".format(
                    n=tel.get("n_calls", 0))
            else:
                inner = (
                    "<table class='detail'><thead><tr>"
                    "<th>bay</th><th>n_blocks</th><th>cur_tard</th><th>new_tard</th>"
                    "<th>&Delta;tard</th><th>wall(s)</th></tr></thead><tbody>"
                    + "".join(brows) + "</tbody></table>"
                )
            summary_line = (
                "calls={c}, fired={f}, work-bays seen={s}, improved={i}, "
                "z1 {zb}&rarr;{za}, bay-wall&Sigma;={w}s".format(
                    c=tel.get("n_calls", 0),
                    f=("yes" if tel.get("fired") else "no"),
                    s=tel.get("n_bays_seen", 0), i=tel.get("n_bays_improved", 0),
                    zb=_fmt0(tel.get("z1_before")), za=_fmt0(tel.get("z1_after")),
                    w=_fmt(tel.get("sum_bay_wall"), 1),
                )
            )
            detail_sections.append(
                "<details><summary><b>{inst}</b> &mdash; {sl}</summary>{inner}</details>".format(
                    inst=esc(r["instance"]), sl=summary_line, inner=inner)
            )

    # --- findings -----------------------------------------------------------
    findings = build_findings(records, totals)
    findings_html = "<ul>" + "".join(f"<li>{esc(f)}</li>" for f in findings) + "</ul>"

    # --- totals block -------------------------------------------------------
    t = totals
    comp_block = ""
    if t.get("competitor_set1_total") is not None:
        gap_base = (t["sum_base_obj_both"] - t["competitor_set1_total"]) if t.get("sum_base_obj_both") is not None else None
        gap_pb = (t["sum_perbay_obj_both"] - t["competitor_set1_total"]) if t.get("sum_perbay_obj_both") is not None else None
        comp_block = (
            "<div class='card'><h3>vs Competitor (set1 official)</h3>"
            "<p>Competitor set1 total: <b>{ct}</b></p>"
            "<p>Our BASE total: {bt} (gap {gb})</p>"
            "<p>Our PERBAY total: {pt} (gap {gp})</p>"
            "<p class='muted'>Totals computed over instances feasible in BOTH legs; "
            "competitor total is the full set1 official.</p>"
            "</div>".format(
                ct=_fmt(t["competitor_set1_total"]),
                bt=_fmt(t.get("sum_base_obj_both")), gb=(f"{gap_base:+,.0f}" if gap_base is not None else "&mdash;"),
                pt=_fmt(t.get("sum_perbay_obj_both")), gp=(f"{gap_pb:+,.0f}" if gap_pb is not None else "&mdash;"),
            )
        )

    total_d = None
    total_dpct = None
    if t.get("sum_base_obj_both") is not None and t.get("sum_perbay_obj_both") is not None:
        total_d = t["sum_perbay_obj_both"] - t["sum_base_obj_both"]
        total_dpct = (total_d / t["sum_base_obj_both"] * 100.0) if t["sum_base_obj_both"] else 0.0

    cfg_line = "instances={i} (n={n}) &middot; TL={tl}s &middot; tag={tag} &middot; generated={dt}".format(
        i=esc(cfg["instances_spec"]), n=len(records), tl=cfg["timelimit"],
        tag=esc(cfg.get("tag") or "&mdash;"), dt=esc(cfg["generated"]))

    head = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OGC2026 Pipeline Audit</title>
<style>
 :root{--good:#1a7f37;--bad:#b91c1c;--neu:#6b7280;--bg:#0f172a;--card:#1e293b;}
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
 td.verdict{font-weight:700;text-transform:uppercase;font-size:11px;}
 td.verdict.good{color:var(--good);}
 td.verdict.bad{color:var(--bad);}
 td.verdict.neu{color:var(--neu);}
 .good{color:var(--good);} .bad{color:var(--bad);} .muted,.neu{color:var(--neu);}
 h2{margin:26px 0 10px;font-size:16px;border-bottom:2px solid #cbd5e1;padding-bottom:5px;}
 details{background:#fff;border:1px solid #e2e8f0;border-radius:6px;margin:6px 0;padding:6px 12px;}
 summary{cursor:pointer;font-size:12px;}
 table.detail{margin:8px 0;width:auto;min-width:420px;}
 .findings{background:#fff;border-left:4px solid #2563eb;padding:12px 18px;border-radius:0 6px 6px 0;}
 .findings li{margin:4px 0;}
</style></head><body>
<header><h1>OGC2026 Pipeline Audit &mdash; BASE vs PERBAY</h1>
<div class="cfg">""" + cfg_line + "</div></header><div class='wrap'>"

    cards = (
        "<div class='cards'>"
        "<div class='card'><h3>BASE total (both-feasible)</h3>"
        "<p class='big'>{bt}</p><p class='muted'>{nb} instances counted</p></div>"
        "<div class='card'><h3>PERBAY total (both-feasible)</h3>"
        "<p class='big'>{pt}</p><p class='muted'>&Delta; {td} ({tp})</p></div>"
        "<div class='card'><h3>Verdicts</h3>"
        "<p><span class='good'>wins {w}</span> &middot; <span class='neu'>ties {ti}</span> "
        "&middot; <span class='bad'>regressions {rg}</span></p></div>"
        "<div class='card'><h3>Feasibility</h3>"
        "<p>BASE infeasible/crash: <b class='{bcls}'>{bi}</b></p>"
        "<p>PERBAY infeasible/crash: <b class='{pcls}'>{pi}</b></p></div>"
        "<div class='card'><h3>Max wall</h3>"
        "<p class='big {wcls}'>{mw}s</p><p class='muted'>TL={tl}s ({ok})</p></div>"
        "{comp}"
        "</div>".format(
            bt=_fmt(t.get("sum_base_obj_both")), nb=t.get("n_both_feasible", 0),
            pt=_fmt(t.get("sum_perbay_obj_both")),
            td=(f"{total_d:+,.0f}" if total_d is not None else "&mdash;"),
            tp=(f"{total_dpct:+.2f}%" if total_dpct is not None else "&mdash;"),
            w=t.get("n_wins", 0), ti=t.get("n_ties", 0), rg=t.get("n_regressions", 0),
            bi=t.get("base_infeasible", 0), pi=t.get("perbay_infeasible", 0),
            bcls=("bad" if t.get("base_infeasible") else "good"),
            pcls=("bad" if t.get("perbay_infeasible") else "good"),
            mw=_fmt(t.get("max_wall"), 1),
            wcls=("bad" if (t.get("max_wall") or 0) > cfg["timelimit"] + 1.0 else "good"),
            tl=cfg["timelimit"],
            ok=("OK &le; TL" if (t.get("max_wall") or 0) <= cfg["timelimit"] + 1.0 else "OVER TL!"),
            comp=comp_block,
        )
    )

    table = (
        "<h2>Per-instance</h2>"
        "<table id='tbl'><thead><tr>"
        "<th onclick='sortT(0)'>instance</th><th onclick='sortT(1)'>n_blk</th>"
        "<th onclick='sortT(2)'>n_bay</th><th>w1/w2/w3</th>"
        "<th onclick='sortT(4)'>BASE obj</th><th>z1/z2/z3</th>"
        "<th onclick='sortT(6)'>PERBAY obj</th><th>z1/z2/z3</th>"
        "<th onclick='sortT(8)'>&Delta;obj</th><th onclick='sortT(9)'>&Delta;%</th>"
        "<th onclick='sortT(10)'>BASE wall</th><th onclick='sortT(11)'>PB wall</th>"
        "<th>fired?</th><th onclick='sortT(13)'>bays&uarr;</th>"
        "<th onclick='sortT(14)'>comp obj</th><th>verdict</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )

    details = (
        "<h2>Per-bay perbay detail (the whole process)</h2>" + "".join(detail_sections)
        if detail_sections else
        "<h2>Per-bay perbay detail</h2><p class='muted'>No perbay telemetry recorded.</p>"
    )

    findings_block = "<h2>Findings (auto-generated)</h2><div class='findings'>" + findings_html + "</div>"

    js = """
<script>
function sortT(c){
 var t=document.getElementById('tbl'),b=t.tBodies[0],r=[].slice.call(b.rows);
 var asc=t.getAttribute('data-c')==c&&t.getAttribute('data-a')!='1';
 t.setAttribute('data-c',c);t.setAttribute('data-a',asc?'1':'0');
 r.sort(function(x,y){
  var a=x.cells[c].innerText.replace(/[,%s]/g,''),d=y.cells[c].innerText.replace(/[,%s]/g,'');
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
    # fire rate
    fired = sum(1 for r in records if r["_tel_summary"].get("fired"))
    n = len(records)
    out.append(f"perbay fire-rate: {fired}/{n} instances had improve() fire "
               f"(at least one work-bay solved).")

    # total movement
    if t.get("sum_base_obj_both") is not None and t.get("sum_perbay_obj_both") is not None:
        d = t["sum_perbay_obj_both"] - t["sum_base_obj_both"]
        dpct = (d / t["sum_base_obj_both"] * 100.0) if t["sum_base_obj_both"] else 0.0
        verb = "reduced" if d < 0 else ("increased" if d > 0 else "did not change")
        out.append(f"Total objective (both-feasible {t.get('n_both_feasible',0)} insts): "
                   f"perbay {verb} obj by {abs(d):,.0f} ({dpct:+.2f}%) "
                   f"[{t['sum_base_obj_both']:,.0f} -> {t['sum_perbay_obj_both']:,.0f}].")

    # top-3 perbay wins (most negative delta)
    deltas = [(r["instance"], r["delta_obj"]) for r in records
              if r.get("delta_obj") is not None and r["delta_obj"] < 0]
    deltas.sort(key=lambda x: x[1])
    if deltas:
        top = ", ".join(f"{nm} ({d:+,.0f})" for nm, d in deltas[:3])
        out.append(f"perbay helped most on: {top}.")
    else:
        out.append("perbay produced no net objective improvement on any instance "
                   "(all ties or regressions).")

    # regressions / infeasibles
    regs = [r["instance"] for r in records if r["winner"] == "regression"]
    if regs:
        out.append(f"REGRESSIONS / infeasible-under-perbay: {', '.join(regs)}.")
    else:
        out.append("No regressions: perbay never made an instance worse or infeasible.")

    if t.get("base_infeasible") or t.get("perbay_infeasible"):
        out.append(f"Infeasible/crash counts -- BASE: {t.get('base_infeasible',0)}, "
                   f"PERBAY: {t.get('perbay_infeasible',0)} (each costs ~ -R/2 in scoring).")

    if t.get("max_wall") is not None:
        out.append(f"Max wall over all legs: {t['max_wall']:.1f}s "
                   f"(TL was {t.get('timelimit')}s).")
    return out


# --- totals -------------------------------------------------------------------
def compute_totals(records, competitor, instances_spec, timelimit):
    sum_base = 0.0
    sum_pb = 0.0
    n_both = 0
    n_wins = n_ties = n_regs = 0
    base_inf = pb_inf = 0
    max_wall = 0.0
    for r in records:
        base, pb = r["base"], r["perbay"]
        for leg in (base, pb):
            if leg.get("wall") is not None:
                max_wall = max(max_wall, leg["wall"])
        if not base.get("feasible"):
            base_inf += 1
        if not pb.get("feasible"):
            pb_inf += 1
        if base.get("feasible") and pb.get("feasible") and \
           base.get("obj") is not None and pb.get("obj") is not None:
            sum_base += base["obj"]
            sum_pb += pb["obj"]
            n_both += 1
        w = r["winner"]
        if w == "perbay":
            n_wins += 1
        elif w == "regression":
            n_regs += 1
        else:
            n_ties += 1

    # competitor set1 total only meaningful when running set1 / all40
    up = (instances_spec or "").upper()
    comp_total = _COMPETITOR_SET1_TOTAL if up in ("SET1", "ALL40") and competitor else None

    return {
        "instances_spec": instances_spec,
        "timelimit": timelimit,
        "sum_base_obj_both": (sum_base if n_both else None),
        "sum_perbay_obj_both": (sum_pb if n_both else None),
        "n_both_feasible": n_both,
        "n_wins": n_wins, "n_ties": n_ties, "n_regressions": n_regs,
        "base_infeasible": base_inf, "perbay_infeasible": pb_inf,
        "max_wall": (max_wall if records else None),
        "competitor_set1_total": comp_total,
    }


# --- main ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="OGC2026 pipeline audit (BASE vs PERBAY)")
    ap.add_argument("--instances", default="SET1",
                    help="comma list (prob_13,prob_14) or SET1|SET2|ALL40")
    ap.add_argument("--timelimit", type=float, default=120.0)
    ap.add_argument("--out", default=os.path.join("notes", "pipeline-audit"),
                    help="output basename (no extension)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    names = parse_instances(args.instances)
    if not names:
        print("No instances selected.", file=sys.stderr)
        sys.exit(2)

    # Resolve --out relative to project root (so it lands where expected even if
    # cwd differs).
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

    print(f"[audit] importing solver from {_SRC}", flush=True)
    import myalgorithm
    from utils import check_feasibility
    algorithm = myalgorithm.algorithm

    competitor = load_competitor()
    print(f"[audit] competitor entries: {len(competitor)}", flush=True)

    records = []
    for idx, name in enumerate(names, 1):
        print(f"[audit] ({idx}/{len(names)}) {name}: loading meta...", flush=True)
        try:
            meta = instance_meta(load_instance(name))
        except Exception as e:
            print(f"[audit]   FAILED to load {name}: {e}", flush=True)
            continue

        print(f"[audit]   {name}: BASE leg (OGC_PERBAY=0) TL={args.timelimit}s...", flush=True)
        base, _ = run_leg(algorithm, check_feasibility, name, args.timelimit, perbay_on=False)
        print(f"[audit]     BASE: status={base['status']} feasible={base['feasible']} "
              f"obj={base['obj']} wall={base['wall']:.1f}s" if base['wall'] is not None
              else f"[audit]     BASE: status={base['status']}", flush=True)

        print(f"[audit]   {name}: PERBAY leg (OGC_PERBAY=1) TL={args.timelimit}s...", flush=True)
        pb, telemetry = run_leg(algorithm, check_feasibility, name, args.timelimit, perbay_on=True)
        tel_summary = summarize_telemetry(telemetry)
        print(f"[audit]     PERBAY: status={pb['status']} feasible={pb['feasible']} "
              f"obj={pb['obj']} wall={pb['wall']:.1f}s fired={tel_summary['fired']} "
              f"bays_improved={tel_summary['n_bays_improved']}" if pb['wall'] is not None
              else f"[audit]     PERBAY: status={pb['status']}", flush=True)

        verdict, dobj, dpct, dz1 = compute_verdict(base, pb)
        comp = competitor.get(name, {})
        rec = {
            "instance": name,
            "n_blocks": meta["n_blocks"],
            "n_bays": meta["n_bays"],
            "weights": meta["weights"],
            "bay_sizes": meta["bay_sizes"],
            "base": base,
            "perbay": pb,
            "perbay_telemetry": telemetry,
            "delta_obj": dobj,
            "delta_pct": dpct,
            "delta_z1": dz1,
            "winner": verdict,
            "competitor_obj": comp.get("obj"),
            "_tel_summary": tel_summary,
        }
        records.append(rec)

    totals = compute_totals(records, competitor, args.instances, args.timelimit)

    # --- write JSON (drop the private _tel_summary; it's derivable) ----------
    json_records = []
    for r in records:
        rr = dict(r)
        rr.pop("_tel_summary", None)
        json_records.append(rr)
    json_path = out_base + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"config": cfg, "totals": totals, "instances": json_records},
                  f, indent=2, ensure_ascii=False)
    print(f"[audit] wrote {json_path}", flush=True)

    # --- write HTML ---------------------------------------------------------
    html_path = out_base + ".html"
    html = render_html(records, totals, cfg)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[audit] wrote {html_path}", flush=True)

    print("[audit] DONE.", flush=True)
    print(f"[audit] JSON: {json_path}")
    print(f"[audit] HTML: {html_path}")


if __name__ == "__main__":
    main()
