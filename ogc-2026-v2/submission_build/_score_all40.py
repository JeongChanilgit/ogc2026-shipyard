"""_score_all40.py [TL] [PAR] -- run the SUBMISSION on ALL 40 instances at TL
(default 600s = 10min each), PAR in parallel (default 4 -> 16 of 20 cores).
Writes a running summary so progress is inspectable mid-run."""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TL = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
PAR = int(sys.argv[2]) if len(sys.argv) > 2 else 4
RESDIR = os.path.join(THIS, "_score_res")
os.makedirs(RESDIR, exist_ok=True)
SUMMARY = "C:/claude-develop/OGC2026/submissions/v3_all40_tl600.txt"


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
    s1 = [r for r in rows if r["i"] <= 20]
    s2 = [r for r in rows if r["i"] > 20]

    def tot(rs):
        return sum(r["obj"] for r in rows if r in rs and r.get("obj") is not None)
    set1 = sum(r["obj"] for r in s1 if r.get("obj") is not None)
    set2 = sum(r["obj"] for r in s2 if r.get("obj") is not None)
    feas = sum(1 for r in rows if r.get("feas"))
    m1 = sum(1 for r in rows if not r.get("feas"))
    with open(SUMMARY, "w", encoding="utf-8") as f:
        f.write(f"=== V3 submission (v3postproc-seq) ALL40 @TL={TL:.0f}s  4-core-affinity x4 ===\n")
        f.write(f"elapsed={elapsed:.0f}s  done={len(rows)}/40  feasible={feas}  infeasible(-1)={m1}\n")
        f.write(f"set1_total={set1:.0f}  set2_total={set2:.0f}  TOTAL={set1+set2:.0f}\n")
        f.write("-" * 78 + "\n")
        f.write(f"{'inst':>8} {'obj':>14} {'z1':>8} {'z3':>8} {'feas':>5} {'wall':>7} {'stage':>8}\n")
        for r in rows:
            f.write(f"{'prob_'+str(r['i']):>8} {str(r.get('obj')):>14} "
                    f"{str(r.get('z1')):>8} {str(r.get('z3')):>8} "
                    f"{str(r.get('feas')):>5} {str(r.get('wall')):>6}s {str(r.get('stage')):>8}\n")
        f.flush()
    json.dump({"tl": TL, "set1": set1, "set2": set2, "total": set1 + set2,
               "feasible": feas, "minus1": m1, "done": len(rows), "rows": rows},
              open(SUMMARY.replace(".txt", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


# disjoint 4-core sets -> faithful 4-core/instance eval; cores 16-19 free for OS/driver
SLOTS = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]


def main():
    for i in range(1, 41):
        if os.path.exists(outf(i)):
            os.remove(outf(i))
    pending = list(range(1, 41))
    running = {}            # i -> (popen, slot)
    free_slots = list(range(len(SLOTS)))
    t0 = time.time()
    print(f"[score] ALL40 TL={TL} 4-core-affinity slots={SLOTS}", flush=True)
    while pending or running:
        while pending and free_slots:
            i = pending.pop(0)
            slot = free_slots.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            log = os.path.join(RESDIR, f"log{i}.txt")
            p = subprocess.Popen([PY, os.path.join(THIS, "_score_one.py"),
                                  str(i), str(TL), outf(i), cores],
                                 cwd=THIS, stdout=open(log, "w"),
                                 stderr=subprocess.STDOUT)
            running[i] = (p, slot)
            print(f"[launch] prob_{i} cores={cores}  ({len(running)} running / {len(pending)} pending)", flush=True)
        done = [i for i, (p, s) in running.items() if p.poll() is not None]
        for i in done:
            _, slot = running.pop(i)
            free_slots.append(slot)
            try:
                r = json.load(open(outf(i), encoding="utf-8"))
                print(f"[DONE] prob_{i} obj={r.get('obj')} z1={r.get('z1')} "
                      f"feas={r.get('feas')} wall={r.get('wall')}s", flush=True)
            except Exception:
                print(f"[DONE] prob_{i} (no result file -- crash?)", flush=True)
            write_summary(time.time() - t0)
        time.sleep(2)
    write_summary(time.time() - t0)
    print(f"[score] ALL DONE in {time.time()-t0:.0f}s -> {SUMMARY}", flush=True)


if __name__ == "__main__":
    main()
