"""_v2v3_dev.py "label" "note" "ENV=v ..."  -- develop the SUBMISSION v2+v3
(myalgorithm_fix, OGC_NO_V1=1) toward: set1 z1=0 on all 20 + lower z3.

Runs set1 (prob_1..20) 4-core-affinity x4, records per-instance z1/z3/obj +
(z1=0 count, Sigma z3, total) per labeled config, regenerates a dev-log HTML.
"""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
BASE = "C:/claude-develop/OGC2026"
RESDIR = os.path.join(THIS, "_v2v3_res")
os.makedirs(RESDIR, exist_ok=True)
LOG = f"{BASE}/submissions/v2v3_set1_devlog.json"
HTML = f"{BASE}/ogc-2026-v2/docs/v2v3-set1-devlog.html"
SLOTS = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]
PROBS = list(range(1, 21))
TL = float(os.environ.get("V2V3_TL", "150"))

# competitor set1 (official 2026-06-15) per-instance z3 + obj
try:
    _c = json.load(open(f"{BASE}/notes/competitor-2026-06-15.json", encoding="utf-8"))["competitor"]
    CREF = {i: {"z3": _c[f"prob_{i}"]["z3"], "obj": _c[f"prob_{i}"]["obj"]} for i in PROBS if f"prob_{i}" in _c}
except Exception:
    CREF = {}


def outf(i):
    return os.path.join(RESDIR, f"d{i}.json")


def run_set(extra_env):
    for i in PROBS:
        if os.path.exists(outf(i)):
            os.remove(outf(i))
    pending = list(PROBS)
    running = {}
    free = list(range(len(SLOTS)))
    while pending or running:
        while pending and free:
            i = pending.pop(0)
            slot = free.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            env = dict(os.environ)
            env["OGC_NO_V1"] = "1"            # v2+v3 only, no v1
            env.update(extra_env)
            log = os.path.join(RESDIR, f"log{i}.txt")
            p = subprocess.Popen([PY, os.path.join(THIS, "_score_one_fix.py"),
                                  str(i), str(TL), outf(i), cores],
                                 cwd=THIS, stdout=open(log, "w"),
                                 stderr=subprocess.STDOUT, env=env)
            running[i] = (p, slot)
        done = [i for i, (p, s) in running.items() if p.poll() is not None]
        for i in done:
            _, slot = running.pop(i)
            free.append(slot)
        time.sleep(2)
    rows = []
    for i in PROBS:
        try:
            r = json.load(open(outf(i), encoding="utf-8"))
            rows.append({"i": i, "obj": r.get("obj"), "z1": r.get("z1"),
                         "z3": r.get("z3"), "feas": r.get("feas"), "wall": r.get("wall")})
        except Exception:
            rows.append({"i": i, "obj": None, "feas": False})
    return rows


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "unlabeled"
    note = sys.argv[2] if len(sys.argv) > 2 else ""
    env_note = sys.argv[3] if len(sys.argv) > 3 else ""
    extra_env = {}
    for kv in env_note.split():
        if "=" in kv:
            k, v = kv.split("=", 1)
            extra_env[k] = v
    t0 = time.time()
    print(f"[v2v3-dev] '{label}' TL={TL} env={extra_env}", flush=True)
    rows = run_set(extra_env)
    total = sum(r["obj"] for r in rows if r.get("obj") is not None)
    z1zero = sum(1 for r in rows if r.get("z1") == 0)
    sumz3 = sum(r["z3"] for r in rows if r.get("z3") is not None)
    feas = sum(1 for r in rows if r.get("feas"))
    entry = {"label": label, "note": note, "env": env_note, "tl": TL,
             "total": total, "z1zero": z1zero, "sumz3": sumz3, "feas": feas,
             "n": len(rows), "rows": rows, "elapsed": round(time.time() - t0)}
    db = {"runs": []}
    if os.path.exists(LOG):
        try:
            db = json.load(open(LOG, encoding="utf-8"))
        except Exception:
            pass
    db.setdefault("runs", []).append(entry)
    json.dump(db, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_html(db)
    print(f"[v2v3-dev] '{label}' total={total:,.0f} z1=0:{z1zero}/20 Sz3={sumz3:,.0f} "
          f"feas={feas}/20 ({entry['elapsed']}s) -> {HTML}", flush=True)


def write_html(db):
    comp_total = 931465
    comp_z3 = sum(v["z3"] for v in CREF.values())
    runs = db.get("runs", [])
    best_t = min((r["total"] for r in runs if r.get("total")), default=None)
    best_z = max((r["z1zero"] for r in runs), default=0)
    body = ""
    for r in reversed(runs):
        rm = {x["i"]: x for x in r["rows"]}
        cells = ""
        for i in PROBS:
            x = rm.get(i, {})
            z1 = x.get("z1"); z3 = x.get("z3")
            cz3 = CREF.get(i, {}).get("z3")
            z1cls = "good" if z1 == 0 else ("bad" if (z1 or 0) > 0 else "mut")
            z3cls = ""
            if z3 is not None and cz3 is not None:
                z3cls = "good" if z3 <= cz3 * 1.5 else ("warn" if z3 <= cz3 * 4 else "bad")
            cells += (f"<td class='{z1cls}'>{'INF' if x.get('obj') is None else z1}"
                      f"<div class='sub {z3cls}'>z3 {z3}</div></td>")
        tcls = "best" if r.get("total") == best_t else ""
        zcls = "best" if r.get("z1zero") == best_z else ""
        body += (f"<tr><td class='l'><b>{r['label']}</b><div class='sub'>{r.get('note','')}"
                 f"{('  ['+r['env']+']') if r.get('env') else ''}  ·TL{r.get('tl')}</div></td>"
                 f"<td class='{zcls}'><b>{r.get('z1zero')}/20</b></td>"
                 f"<td class='{tcls}'>{format(r.get('total'),',.0f') if r.get('total') else '-'}</td>"
                 f"<td>{format(r.get('sumz3'),',.0f') if r.get('sumz3') is not None else '-'}</td>"
                 f"{cells}<td class='sub'>{r.get('feas')}/20·{r.get('elapsed')}s</td></tr>")
    chead = "".join(f"<th>p{i}</th>" for i in PROBS)
    crow = "".join(f"<td class='mut'>0<div class='sub'>z3 {CREF.get(i,{}).get('z3','-')}</div></td>" for i in PROBS)
    html = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><title>v2+v3 set1 z1=0 + z3 개발로그</title>
<style>
 body{margin:0;background:#0e1014;color:#e8ebf1;font:12px/1.45 Segoe UI,sans-serif}
 .wrap{max-width:1500px;margin:0 auto;padding:20px}
 h1{font-size:19px;margin:0 0 2px} .sub{color:#8b93a3;font-size:10px}
 table{border-collapse:collapse;width:100%;margin-top:12px;font-variant-numeric:tabular-nums}
 th,td{padding:5px 6px;text-align:right;border-bottom:1px solid #232833;vertical-align:top}
 th{color:#9aa3b2;position:sticky;top:0;background:#0e1014;font-size:11px}
 td.l,th.l{text-align:left;max-width:240px} .good{color:#7ee787} .warn{color:#f0c674} .bad{color:#ff6b6b} .mut{color:#8b93a3}
 .best{color:#7ee787;font-weight:700} b{color:#5ad1c7}
 .note{background:#161a21;border:1px solid #232833;border-radius:8px;padding:11px 14px;margin:10px 0;font-size:12px}
</style></head><body><div class="wrap">
<h1>v2+v3 set1 — z1=0 + z3↓ 개발로그 <span class="sub">(v1 없이, 자동갱신 60s)</span></h1>
<div class="note"><b>목표</b>: 제출본 v2(unified_greedy)+v3(postproc)만으로(<b>OGC_NO_V1=1</b>) set1 <b>z1=0 (20/20)</b> + <b>z3 낮추기</b>.
 경쟁자 set1 총=<b>931,465</b>, Σz3=<b>""" + f"{comp_z3:,}" + """</b>. 셀=z1값(초록=0), 아래 z3(초록≤경쟁1.5×). 최신이 위.</div>
<table><thead><tr><th class="l">config</th><th>z1=0</th><th>총obj</th><th>Σz3</th>""" + chead + """<th>feas</th></tr>
<tr><td class="l mut">경쟁자</td><td class="mut">20/20</td><td class="mut">931,465</td><td class="mut">""" + f"{comp_z3:,}" + """</td>""" + crow + """<td class="mut">-</td></tr>
</thead><tbody>""" + body + """</tbody></table></div></body></html>"""
    open(HTML, "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
