"""_verify_all40.py [TL] [PAR] -- FINAL pre-submission verification of the EXTRACTED
SUBMISSION ZIP (_verify_zip/) on ALL 40 instances at TL, PAR in parallel with disjoint
4-core affinity.  Runs the clean extracted zip (exactly what the eval server runs), not
the dual-tree top-level.  Gate: feasible 40/40 (never -1) + obj baseline.
"""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
ZIPDIR = os.path.join(THIS, "_verify_zip")
PY = sys.executable
TL = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
PAR = int(sys.argv[2]) if len(sys.argv) > 2 else 4
RESDIR = os.path.join(THIS, "_verify_res")
os.makedirs(RESDIR, exist_ok=True)
SUMMARY = os.path.join(THIS, "_verify_all40.txt")
SLOTS = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]][:PAR]


def outf(i):
    return os.path.join(RESDIR, f"r{i}.json")


def write_summary(elapsed):
    rows = []
    for i in range(1, 41):
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
        f.write(f"=== ZIP VERIFY (cap30bl) ALL40 @TL={TL:.0f}s  4-core-affinity x{PAR} ===\n")
        f.write(f"elapsed={elapsed:.0f}s  done={len(rows)}/40  feasible={feas}  "
                f"infeasible(-1)={m1}  maxwall={maxwall:.0f}s\n")
        f.write(f"set1={s1:.0f}  set2={s2:.0f}  TOTAL={s1+s2:.0f}\n")
        f.write("-" * 82 + "\n")
        f.write(f"{'inst':>8} {'obj':>14} {'z1':>9} {'z3':>8} {'feas':>5} {'wall':>7}\n")
        for r in rows:
            f.write(f"{'prob_'+str(r['i']):>8} {str(r.get('obj')):>14} "
                    f"{str(r.get('z1')):>9} {str(r.get('z3')):>8} "
                    f"{str(r.get('feas')):>5} {str(r.get('wall')):>6}s\n")
    json.dump({"tl": TL, "set1": s1, "set2": s2, "total": s1 + s2, "feasible": feas,
               "minus1": m1, "done": len(rows), "maxwall": maxwall, "rows": rows},
              open(SUMMARY.replace(".txt", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def main():
    assert os.path.exists(os.path.join(ZIPDIR, "myalgorithm.py")), "extract zip into _verify_zip first"
    for i in range(1, 41):
        if os.path.exists(outf(i)):
            os.remove(outf(i))
    pending = list(range(1, 41))
    running = {}
    free_slots = list(range(len(SLOTS)))
    t0 = time.time()
    print(f"[verify] cap30bl ZIP ALL40 TL={TL} PAR={PAR} cwd={ZIPDIR}", flush=True)
    while pending or running:
        while pending and free_slots:
            i = pending.pop(0)
            slot = free_slots.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            log = os.path.join(RESDIR, f"log{i}.txt")
            p = subprocess.Popen(
                [PY, os.path.join(ZIPDIR, "_score_one.py"), str(i), str(TL), outf(i), cores],
                cwd=ZIPDIR, stdout=open(log, "w"), stderr=subprocess.STDOUT)
            running[i] = (p, slot)
            print(f"[launch] prob_{i} cores={cores} ({len(running)}r/{len(pending)}p)", flush=True)
        done = [i for i, (p, s) in running.items() if p.poll() is not None]
        for i in done:
            _, slot = running.pop(i)
            free_slots.append(slot)
            try:
                r = json.load(open(outf(i), encoding="utf-8"))
                tag = "OK" if r.get("feas") else "!!! -1"
                print(f"[{tag}] prob_{i} obj={r.get('obj')} z1={r.get('z1')} "
                      f"wall={r.get('wall')}s", flush=True)
            except Exception:
                print(f"[DONE] prob_{i} (no result -- CRASH?)", flush=True)
            write_summary(time.time() - t0)
        time.sleep(2)
    write_summary(time.time() - t0)
    j = json.load(open(SUMMARY.replace(".txt", ".json"), encoding="utf-8"))
    verdict = "PASS (never -1)" if j["minus1"] == 0 and j["feasible"] == 40 \
        else f"FAIL (feasible={j['feasible']}/40 -1={j['minus1']})"
    print(f"[verify] DONE {time.time()-t0:.0f}s :: {verdict}  TOTAL={j['total']:.0f} "
          f"(set1={j['set1']:.0f} set2={j['set2']:.0f}) -> {SUMMARY}", flush=True)


if __name__ == "__main__":
    main()
