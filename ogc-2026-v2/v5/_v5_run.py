"""_v5_run.py -- run v5 AND current method on 3 set1 + 3 set2 instances,
4-core affinity x4 parallel, save solutions (for 3D) + print comparison."""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
RESDIR = os.path.join(THIS, "_v5_res")
os.makedirs(RESDIR, exist_ok=True)
SLOTS = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]
SET1 = [4, 12, 20]
SET2 = [21, 30, 38]
JOBS = ([(i, 300.0, m) for i in SET1 for m in ("v5",)]
        + [(i, 480.0, m) for i in SET2 for m in ("v5",)])
SUMMARY = os.path.join("C:/claude-develop/OGC2026/submissions", "v5_compare.txt")


def outf(i, m):
    return os.path.join(RESDIR, f"r{i}_{m}.json")


def write_summary(elapsed):
    rows = {}
    for (i, tl, m) in JOBS:
        f = outf(i, m)
        if os.path.exists(f):
            try:
                rows[(i, m)] = json.load(open(f, encoding="utf-8"))
            except Exception:
                pass
    with open(SUMMARY, "w", encoding="utf-8") as fh:
        fh.write(f"=== v5 vs current  (elapsed={elapsed:.0f}s)  4-core-affinity x4 ===\n")
        fh.write(f"{'inst':>8} {'v5_obj':>13} {'v5_z1':>6} {'v5_z3':>6} {'v5_wall':>7}  "
                 f"{'cur_obj':>13} {'cur_z1':>6} {'cur_z3':>6}  {'v5/cur':>7}\n")
        fh.write("-" * 92 + "\n")
        for i in SET1 + SET2:
            v = rows.get((i, "v5")); c = rows.get((i, "cur"))
            def g(d, k):
                return "-" if (d is None or d.get(k) is None) else (f"{d[k]:,.0f}" if isinstance(d.get(k), (int, float)) else str(d[k]))
            ratio = "-"
            if v and c and v.get("obj") and c.get("obj"):
                ratio = f"{v['obj']/c['obj']:.2f}"
            fh.write(f"{'prob_'+str(i):>8} {g(v,'obj'):>13} {g(v,'z1'):>6} {g(v,'z3'):>6} "
                     f"{g(v,'wall'):>6}s  {g(c,'obj'):>13} {g(c,'z1'):>6} {g(c,'z3'):>6}  {ratio:>7}\n")
        fh.flush()


def main():
    for (i, tl, m) in JOBS:
        if os.path.exists(outf(i, m)):
            os.remove(outf(i, m))
    pending = list(JOBS)
    running = {}
    free = list(range(len(SLOTS)))
    t0 = time.time()
    while pending or running:
        while pending and free:
            i, tl, m = pending.pop(0)
            slot = free.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            log = os.path.join(RESDIR, f"log{i}_{m}.txt")
            p = subprocess.Popen([PY, os.path.join(THIS, "_v5_one.py"),
                                  str(i), str(tl), outf(i, m), cores, m],
                                 cwd=THIS, stdout=open(log, "w"), stderr=subprocess.STDOUT)
            running[(i, m)] = (p, slot)
            print(f"[launch] prob_{i} {m} cores={cores} tl={tl}", flush=True)
        done = [k for k, (p, s) in running.items() if p.poll() is not None]
        for k in done:
            _, slot = running.pop(k)
            free.append(slot)
            try:
                r = json.load(open(outf(*k), encoding="utf-8"))
                print(f"[done] prob_{k[0]} {k[1]} obj={r.get('obj')} feas={r.get('feas')} wall={r.get('wall')}s", flush=True)
            except Exception:
                print(f"[done] prob_{k[0]} {k[1]} (no result)", flush=True)
            write_summary(time.time() - t0)
        time.sleep(2)
    write_summary(time.time() - t0)
    print(f"[v5-run] DONE {time.time()-t0:.0f}s -> {SUMMARY}", flush=True)


if __name__ == "__main__":
    main()
