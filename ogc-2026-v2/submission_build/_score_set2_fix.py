"""_score_set2_fix.py [TL] -- run myalgorithm_fix on set2 (prob_21..40) at TL
(default 600), 4-core affinity x4 parallel.  Live per-instance summary with
provenance (base v1/v2) + postproc gain so progress is watchable."""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TL = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
RESDIR = os.path.join(THIS, "_score_res_fix")
os.makedirs(RESDIR, exist_ok=True)
SUMMARY = os.environ.get("OGC_SUMMARY", "C:/claude-develop/OGC2026/submissions/v2v3_set2.txt")
SLOTS = [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]
PROBS = list(range(int(os.environ.get("OGC_PLO", "21")), int(os.environ.get("OGC_PHI", "41"))))


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
    total = sum(r["obj"] for r in rows if r.get("obj") is not None)
    feas = sum(1 for r in rows if r.get("feas"))
    m1 = sum(1 for r in rows if not r.get("feas"))
    nv1 = sum(1 for r in rows if r.get("base") == "v1")
    nv2 = sum(1 for r in rows if r.get("base") == "v2")
    npp = sum(1 for r in rows if r.get("pp_improved"))

    def f(x):
        return "-" if x is None else (f"{x:,.0f}" if isinstance(x, (int, float)) else str(x))

    with open(SUMMARY, "w", encoding="utf-8") as fh:
        fh.write(f"=== myalgorithm_FIX set2 @TL={TL:.0f}s  4-core-affinity x4 ===\n")
        fh.write(f"fixes: v2_cap={os.environ.get('OGC_V2_CAP','90')}s  "
                 f"orig_frac={os.environ.get('OGC_ORIG_FRAC','0.55')}  postproc=full-obj,no-z1-gate\n")
        fh.write(f"elapsed={elapsed:.0f}s  done={len(rows)}/20  feasible={feas}  -1={m1}  "
                 f"base: v1={nv1} v2={nv2}  pp_improved={npp}\n")
        fh.write(f"set2_TOTAL={total:,.0f}\n")
        fh.write("-" * 104 + "\n")
        fh.write(f"{'inst':>8} {'final_obj':>13} {'z1':>7} {'z3':>7} {'base':>5} "
                 f"{'base_obj':>13} {'pp?':>4} {'ppgain':>10} {'wall':>6} {'ppbud':>6}\n")
        for r in rows:
            base_obj = r.get("base_obj")
            obj = r.get("obj")
            ppgain = (base_obj - obj) if (base_obj is not None and obj is not None) else None
            fh.write(f"{'prob_'+str(r['i']):>8} {f(obj):>13} {f(r.get('z1')):>7} "
                     f"{f(r.get('z3')):>7} {str(r.get('base')):>5} {f(base_obj):>13} "
                     f"{('Y' if r.get('pp_improved') else '.'):>4} {f(ppgain):>10} "
                     f"{f(r.get('wall')):>5}s {f(r.get('pp_budget')):>6}\n")
        fh.flush()
    json.dump({"tl": TL, "total": total, "feasible": feas, "minus1": m1,
               "base_v1": nv1, "base_v2": nv2, "pp_improved": npp, "rows": rows},
              open(SUMMARY.replace(".txt", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def main():
    for i in PROBS:
        if os.path.exists(outf(i)):
            os.remove(outf(i))
    pending = list(PROBS)
    running = {}
    free_slots = list(range(len(SLOTS)))
    t0 = time.time()
    print(f"[set2-fix] TL={TL} v2_cap={os.environ.get('OGC_V2_CAP','90')} "
          f"orig_frac={os.environ.get('OGC_ORIG_FRAC','0.55')}", flush=True)
    while pending or running:
        while pending and free_slots:
            i = pending.pop(0)
            slot = free_slots.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            log = os.path.join(RESDIR, f"log{i}.txt")
            p = subprocess.Popen([PY, os.path.join(THIS, "_score_one_fix.py"),
                                  str(i), str(TL), outf(i), cores],
                                 cwd=THIS, stdout=open(log, "w"), stderr=subprocess.STDOUT)
            running[i] = (p, slot)
            print(f"[launch] prob_{i} cores={cores}", flush=True)
        done = [i for i, (p, s) in running.items() if p.poll() is not None]
        for i in done:
            _, slot = running.pop(i)
            free_slots.append(slot)
            try:
                r = json.load(open(outf(i), encoding="utf-8"))
                bo, o = r.get("base_obj"), r.get("obj")
                gain = (bo - o) if (bo is not None and o is not None) else None
                print(f"[DONE] prob_{i} obj={o} base={r.get('base')} "
                      f"ppgain={gain} feas={r.get('feas')} wall={r.get('wall')}s", flush=True)
            except Exception:
                print(f"[DONE] prob_{i} (no result)", flush=True)
            write_summary(time.time() - t0)
        time.sleep(2)
    write_summary(time.time() - t0)
    print(f"[set2-fix] DONE {time.time()-t0:.0f}s -> {SUMMARY}", flush=True)


if __name__ == "__main__":
    main()
