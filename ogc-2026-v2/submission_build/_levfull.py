"""_levfull.py [TL] [PAR] [ARM] [PROBS] -- full-set lever A/B (the adoption judge).

Runs v7's myalgorithm (which HAS the new gated levers) on a set of instances at
TL, with one ARM's lever env injected into the subprocess environment.  4-core
affinity, PAR in parallel.  Judge = full-set total obj + never−1 (user rule).

  ARM   : key into ARMS below (prod / cap20 / cap40 / cap30 / cap20mem / K3 / ...)
  PROBS : ALL40 (default) | SET1 | SET2 | "a-b" | "38,30,..."

Run the SAME PROBS for `prod` and the variant, then compare the two summary JSONs.
prod (all levers off) == the submitted v6/v7 production config, so prod here is the
faithful baseline to beat.

env: C:/Users/peter/anaconda3/envs/ogc2025/python.exe   out: _levfull_<ARM>.txt/.json
"""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
V7 = os.path.join(THIS, "v7")
PY = sys.executable
BASE = "C:/claude-develop/OGC2026"

TL = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
PAR = int(sys.argv[2]) if len(sys.argv) > 2 else 4
ARM = sys.argv[3] if len(sys.argv) > 3 else "prod"
PROBS_ARG = sys.argv[4] if len(sys.argv) > 4 else "ALL40"

ARMS = {
    "prod":     {},
    "cap20":    {"OGC_PP_ACTIVE_CAP": "20"},
    "cap30":    {"OGC_PP_ACTIVE_CAP": "30"},
    "cap40":    {"OGC_PP_ACTIVE_CAP": "40"},
    "cap20mem": {"OGC_PP_ACTIVE_CAP": "20", "OGC_PP_MEMO": "1"},
    "cap30mem": {"OGC_PP_ACTIVE_CAP": "30", "OGC_PP_MEMO": "1"},
    "memo":     {"OGC_PP_MEMO": "1"},
    "K3":       {"OGC_PP_K": "3"},
    "blprobe3": {"OGC_PP_BLPROBE": "3"},
    "tighten":  {"OGC_PP_TIGHTEN": "1"},
}
lever_env = ARMS.get(ARM)
if lever_env is None:
    print(f"unknown ARM '{ARM}'; choices={list(ARMS)}"); sys.exit(1)


def parse_probs(s):
    if s == "ALL40":
        return list(range(1, 41))
    if s == "SET1":
        return list(range(1, 21))
    if s == "SET2":
        return list(range(21, 41))
    if "-" in s and "," not in s:
        a, b = s.split("-"); return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


PROBS = parse_probs(PROBS_ARG)
RESDIR = os.path.join(THIS, f"_levfull_res_{ARM}")
os.makedirs(RESDIR, exist_ok=True)
SUMMARY = os.path.join(THIS, f"_levfull_{ARM}.txt")
# OGC_SLOT_BASE lets two arms run PAIRED on disjoint core slots (same machine load
# -> fair A/B).  e.g. prod base=0 PAR=2 -> slots[0:2]; cap20 base=2 PAR=2 -> slots[2:4].
_ALL_SLOTS = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]
_BASE = int(os.environ.get("OGC_SLOT_BASE", "0"))
SLOTS = _ALL_SLOTS[_BASE:_BASE + PAR]


def outf(i):
    return os.path.join(RESDIR, f"r{i}.json")


def write_summary(elapsed):
    rows = []
    for i in PROBS:
        if os.path.exists(outf(i)):
            try:
                rows.append(json.load(open(outf(i), encoding="utf-8")))
            except Exception:
                pass
    rows.sort(key=lambda r: r["i"])
    s1 = sum(r["obj"] for r in rows if r["i"] <= 20 and r.get("obj") is not None)
    s2 = sum(r["obj"] for r in rows if r["i"] > 20 and r.get("obj") is not None)
    feas = sum(1 for r in rows if r.get("feas"))
    m1 = sum(1 for r in rows if not r.get("feas"))
    maxwall = max((r.get("wall", 0) or 0) for r in rows) if rows else 0
    with open(SUMMARY, "w", encoding="utf-8") as f:
        f.write(f"=== LEVER FULL  ARM={ARM} {lever_env}  TL={TL:.0f}s x{PAR}  "
                f"probs={PROBS_ARG} ===\n")
        f.write(f"elapsed={elapsed:.0f}s done={len(rows)}/{len(PROBS)} "
                f"feasible={feas} infeasible(-1)={m1} maxwall={maxwall:.0f}s\n")
        f.write(f"set1={s1:.0f} set2={s2:.0f} TOTAL={s1+s2:.0f}\n")
        f.write("-" * 78 + "\n")
        f.write(f"{'inst':>8} {'obj':>14} {'z1':>9} {'z3':>8} {'feas':>5} {'wall':>7}\n")
        for r in rows:
            f.write(f"{'prob_'+str(r['i']):>8} {str(r.get('obj')):>14} "
                    f"{str(r.get('z1')):>9} {str(r.get('z3')):>8} "
                    f"{str(r.get('feas')):>5} {str(r.get('wall')):>6}s\n")
    json.dump({"arm": ARM, "env": lever_env, "tl": TL, "probs": PROBS_ARG,
               "set1": s1, "set2": s2, "total": s1 + s2, "feasible": feas,
               "minus1": m1, "done": len(rows), "maxwall": maxwall, "rows": rows},
              open(SUMMARY.replace(".txt", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def main():
    assert os.path.exists(os.path.join(V7, "_levfull_one.py"))
    for i in PROBS:
        if os.path.exists(outf(i)):
            os.remove(outf(i))
    child_env = dict(os.environ, **lever_env)
    pending = list(PROBS)
    running = {}
    free_slots = list(range(len(SLOTS)))
    t0 = time.time()
    print(f"[levfull] ARM={ARM} {lever_env} TL={TL} probs={PROBS_ARG} "
          f"slots={SLOTS}", flush=True)
    while pending or running:
        while pending and free_slots:
            i = pending.pop(0)
            slot = free_slots.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            log = os.path.join(RESDIR, f"log{i}.txt")
            p = subprocess.Popen(
                [PY, os.path.join(V7, "_levfull_one.py"), str(i), str(TL),
                 outf(i), cores],
                cwd=V7, env=child_env, stdout=open(log, "w"),
                stderr=subprocess.STDOUT)
            running[i] = (p, slot)
            print(f"[launch] prob_{i} cores={cores} "
                  f"({len(running)} run / {len(pending)} pend)", flush=True)
        done = [i for i, (p, s) in running.items() if p.poll() is not None]
        for i in done:
            _, slot = running.pop(i)
            free_slots.append(slot)
            try:
                r = json.load(open(outf(i), encoding="utf-8"))
                tag = "OK" if r.get("feas") else "!!!-1"
                print(f"[{tag}] prob_{i} obj={r.get('obj')} z1={r.get('z1')} "
                      f"wall={r.get('wall')}s", flush=True)
            except Exception:
                print(f"[DONE] prob_{i} (no result -- crash?)", flush=True)
            write_summary(time.time() - t0)
        time.sleep(2)
    write_summary(time.time() - t0)
    j = json.load(open(SUMMARY.replace(".txt", ".json"), encoding="utf-8"))
    print(f"[levfull] {ARM} DONE {time.time()-t0:.0f}s :: "
          f"TOTAL={j['total']:.0f} (set1={j['set1']:.0f} set2={j['set2']:.0f}) "
          f"feasible={j['feasible']}/{len(PROBS)} -1={j['minus1']} -> {SUMMARY}",
          flush=True)


if __name__ == "__main__":
    main()
