"""_v5_dev.py "label" "note" -- run current v5 on a fixed dev instance set
(4-core affinity x4), append a labeled row to v5_devlog.json, regenerate the
dev-log HTML so every change + its measured effect is documented for the user.

usage: _v5_dev.py "v1-step3-gated" "STEP3 never-worse + worst-K only"
"""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
RESDIR = os.path.join(THIS, "_v5_res")
os.makedirs(RESDIR, exist_ok=True)
LOG = "C:/claude-develop/OGC2026/submissions/v5_devlog.json"
HTML = "C:/claude-develop/OGC2026/ogc-2026-v2/docs/v5-devlog.html"
SLOTS = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]
# fixed dev set: prob_4 (low-cong, v5 optimal), 12 (mid), 20 (congested set1),
#                21 + 38 (congested set2).  TL per instance.
DEVSET = [(4, 150), (12, 220), (20, 300), (21, 420), (38, 480)]
# competitor obj (set1) for reference
REF = {4: 16916, 12: 71509, 20: 80848}


def outf(i):
    return os.path.join(RESDIR, f"dev_{i}.json")


def run_set(extra_env):
    for (i, _tl) in DEVSET:
        if os.path.exists(outf(i)):
            os.remove(outf(i))
    pending = list(DEVSET)
    running = {}
    free = list(range(len(SLOTS)))
    while pending or running:
        while pending and free:
            i, tl = pending.pop(0)
            slot = free.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            env = dict(os.environ); env.update(extra_env)
            log = os.path.join(RESDIR, f"devlog{i}.txt")
            p = subprocess.Popen([PY, os.path.join(THIS, "_v5_one.py"),
                                  str(i), str(tl), outf(i), cores, "v5"],
                                 cwd=THIS, stdout=open(log, "w"),
                                 stderr=subprocess.STDOUT, env=env)
            running[i] = (p, slot)
        done = [i for i, (p, s) in running.items() if p.poll() is not None]
        for i in done:
            _, slot = running.pop(i)
            free.append(slot)
        time.sleep(2)
    rows = []
    for (i, tl) in DEVSET:
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
    env_note = sys.argv[3] if len(sys.argv) > 3 else ""   # e.g. "OGC_V5_STEP3=gated"
    extra_env = {}
    for kv in env_note.split():
        if "=" in kv:
            k, v = kv.split("=", 1)
            extra_env[k] = v
    t0 = time.time()
    print(f"[dev] running '{label}'  env={extra_env}", flush=True)
    rows = run_set(extra_env)
    total = sum(r["obj"] for r in rows if r.get("obj") is not None)
    feas = sum(1 for r in rows if r.get("feas"))
    entry = {"label": label, "note": note, "env": env_note,
             "total": total, "feas": feas, "n": len(rows),
             "rows": rows, "elapsed": round(time.time() - t0)}
    db = {"runs": []}
    if os.path.exists(LOG):
        try:
            db = json.load(open(LOG, encoding="utf-8"))
        except Exception:
            pass
    db.setdefault("runs", []).append(entry)
    json.dump(db, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_html(db)
    print(f"[dev] '{label}' total={total:,.0f} feas={feas}/{len(rows)} "
          f"({entry['elapsed']}s) -> {HTML}", flush=True)


def write_html(db):
    insts = [i for (i, _t) in DEVSET]
    head = "".join(f"<th>prob_{i}{' *' if i in REF else ''}</th>" for i in insts)
    refrow = "".join(f"<td>{REF.get(i, '-') if not isinstance(REF.get(i), int) else format(REF[i], ',')}</td>"
                     if i in REF else "<td class='mut'>-</td>" for i in insts)
    body = ""
    runs = db.get("runs", [])
    best_total = min((r["total"] for r in runs if r.get("total")), default=None)
    for k, r in enumerate(reversed(runs)):
        cells = ""
        rowmap = {x["i"]: x for x in r["rows"]}
        for i in insts:
            x = rowmap.get(i, {})
            o = x.get("obj")
            cls = ""
            if o is not None and i in REF:
                ratio = o / REF[i]
                cls = "good" if ratio < 1.05 else ("warn" if ratio < 2 else "bad")
            txt = "INFEAS" if o is None else f"{o:,.0f}"
            sub = "" if o is None else f"<div class='sub'>z1={x.get('z1')} z3={x.get('z3')}</div>"
            cells += f"<td class='{cls}'>{txt}{sub}</td>"
        tot = r.get("total")
        tcls = "best" if (tot == best_total) else ""
        body += (f"<tr><td class='l'><b>{r['label']}</b>"
                 f"<div class='sub'>{r.get('note', '')}"
                 f"{('  ['+r['env']+']') if r.get('env') else ''}</div></td>"
                 f"{cells}<td class='{tcls}'>{('' if tot is None else format(tot, ',.0f'))}"
                 f"<div class='sub'>feas {r.get('feas')}/{r.get('n')} · {r.get('elapsed')}s</div></td></tr>")
    html = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60">
<title>v5 개발 로그 — 수정사항 & 측정</title>
<style>
 body{margin:0;background:#0e1014;color:#e8ebf1;font:13px/1.5 Segoe UI,sans-serif}
 .wrap{max-width:1280px;margin:0 auto;padding:24px}
 h1{font-size:20px;margin:0 0 2px} .sub{color:#8b93a3;font-size:11px}
 table{border-collapse:collapse;width:100%;margin-top:14px;font-variant-numeric:tabular-nums}
 th,td{padding:7px 9px;text-align:right;border-bottom:1px solid #232833;vertical-align:top}
 th{color:#9aa3b2;position:sticky;top:0;background:#0e1014;font-size:12px}
 td.l,th.l{text-align:left;max-width:260px}
 .good{color:#7ee787} .warn{color:#f0c674} .bad{color:#ff6b6b} .mut{color:#8b93a3}
 .best{color:#7ee787;font-weight:700}
 .sub{color:#8b93a3;font-size:10.5px;font-weight:400}
 .note{background:#161a21;border:1px solid #232833;border-radius:8px;padding:12px 15px;margin:12px 0;font-size:12.5px}
 b{color:#5ad1c7}
</style></head><body><div class="wrap">
<h1>v5 개발 로그 <span class="sub">— 매 수정의 내용·방법·측정 (자동 갱신, 60s)</span></h1>
<div class="note">
 <b>v5 구조</b>: STEP1 z2+z3 배정(CP-SAT) → greedy 초기배치(place_one) → STEP2 베이별 xyo CP-SAT 정제(t 동시최적) → STEP3 tardy 적출·재배정·greedy → loop.<br>
 <b>측정셋</b>: prob_4(저혼잡·v5최적), 12(중), 20(혼잡 set1), 21·38(혼잡 set2). <b>* = 경쟁자 obj 기준</b>(prob_4 16,916 / 12 71,509 / 20 80,848). 색: 초록=경쟁자 1.05×내, 노랑=2×내, 빨강=2×↑.<br>
 <b>판정</b>: full-set 총 obj · feasible. 아래는 최신이 위.
</div>
<table><thead><tr><th class="l">변경 (label / note / env)</th>""" + head + """<th>총합</th></tr>
<tr><td class="l mut">경쟁자(set1 ref)</td>""" + refrow + """<td class="mut">-</td></tr>
</thead><tbody>""" + body + """</tbody></table>
</div></body></html>"""
    open(HTML, "w", encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
