"""_levctl_sweep.py [PROBS] [BUDGET] [ARMSET] [PAR] [COREBASE] -- run _levctl across
many instances in parallel (disjoint 4-core slots) and aggregate the shared-base
deltas.  Robust to cross-instance contention: each instance's arms SHARE its base,
so any base corruption is common-mode and CANCELS in (arm - prod) deltas.

  PROBS  : SET2 (default) | SET1 | ALL40 | "a-b" | "21,38,..."
  ARMSET : cap (default) | other
Aggregates _levctl_res_{i}.json -> net sum of deltas per arm (negative = lever helps).
"""
import subprocess, sys, os, json, time

THIS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PROBS_ARG = sys.argv[1] if len(sys.argv) > 1 else "SET2"
BUDGET = sys.argv[2] if len(sys.argv) > 2 else "60"
ARMSET = sys.argv[3] if len(sys.argv) > 3 else "cap"
PAR = int(sys.argv[4]) if len(sys.argv) > 4 else 4
COREBASE = int(sys.argv[5]) if len(sys.argv) > 5 else 4   # start core (avoid probe on 0-3)


def parse(s):
    if s == "SET2": return list(range(21, 41))
    if s == "SET1": return list(range(1, 21))
    if s == "ALL40": return list(range(1, 41))
    if "-" in s and "," not in s:
        a, b = s.split("-"); return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


PROBS = parse(PROBS_ARG)
ALLCORES = list(range(20))
SLOTS = [ALLCORES[COREBASE + 4 * k: COREBASE + 4 * k + 4] for k in range(PAR)]
SUMMARY = os.path.join(THIS, f"_levctl_sweep_{ARMSET}_{BUDGET}.txt")


def res(i):
    return os.path.join(THIS, f"_levctl_res_{i}.json")


def aggregate(elapsed):
    rows = []
    for i in PROBS:
        if os.path.exists(res(i)):
            try:
                rows.append(json.load(open(res(i), encoding="utf-8")))
            except Exception:
                pass
    rows.sort(key=lambda r: r["prob"])
    arms = list(_levctl_arms())
    tot = {a: 0 for a in arms}
    lines = []
    hdr = f"{'inst':>8} {'base':>14} " + " ".join(f"{a:>13}" for a in arms)
    lines.append(hdr)
    for r in rows:
        a = r["arms"]
        cells = []
        for arm in arms:
            o = a.get(arm, {}).get("obj")
            if o is not None:
                tot[arm] += o
            cells.append(f"{o:>13,.0f}" if o is not None else f"{'-':>13}")
        lines.append(f"prob_{r['prob']:>2} {r['base_obj']:>14,.0f} " + " ".join(cells))
    p = tot.get("prod", 0)
    delta = {a: tot[a] - p for a in arms}
    with open(SUMMARY, "w", encoding="utf-8") as f:
        f.write(f"=== CONTROLLED SWEEP armset={ARMSET} budget={BUDGET}s "
                f"probs={PROBS_ARG} done={len(rows)}/{len(PROBS)} elapsed={elapsed:.0f}s ===\n")
        f.write("\n".join(lines) + "\n")
        f.write("-" * 70 + "\n")
        f.write(f"{'TOTAL':>8} {'':>14} " +
                " ".join(f"{tot[a]:>13,.0f}" for a in arms) + "\n")
        f.write(f"{'Δ vs prod':>8} {'':>14} " +
                " ".join(f"{delta[a]:>+13,.0f}" for a in arms) + "\n")
    print(open(SUMMARY, encoding="utf-8").read(), flush=True)


def _levctl_arms():
    sets = {"cap": ["prod", "cap20", "cap30"],
            "final": ["prod", "cap20", "cap30bl"],
            "other": ["prod", "blocker", "xsmart", "blprobe3", "tighten", "cap30bl"]}
    return sets.get(ARMSET, ["prod"])


def main():
    for i in PROBS:
        if os.path.exists(res(i)):
            os.remove(res(i))
    env = dict(os.environ, OGC_ARMSET=ARMSET)
    pending = list(PROBS)
    running = {}
    free = list(range(len(SLOTS)))
    t0 = time.time()
    print(f"[sweep] {ARMSET} budget={BUDGET} probs={PROBS_ARG} slots={SLOTS}", flush=True)
    while pending or running:
        while pending and free:
            i = pending.pop(0)
            slot = free.pop(0)
            cores = ",".join(map(str, SLOTS[slot]))
            log = os.path.join(THIS, f"_levctl_{i}.log")
            p = subprocess.Popen(
                [PY, os.path.join(THIS, "_levctl.py"), str(i), BUDGET, cores],
                cwd=THIS, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
            running[i] = (p, slot)
            print(f"[launch] prob_{i} cores={cores} ({len(running)}r/{len(pending)}p)", flush=True)
        done = [i for i, (p, s) in running.items() if p.poll() is not None]
        for i in done:
            _, slot = running.pop(i)
            free.append(slot)
            print(f"[done] prob_{i}", flush=True)
            aggregate(time.time() - t0)
        time.sleep(2)
    aggregate(time.time() - t0)
    print(f"[sweep] DONE {time.time()-t0:.0f}s -> {SUMMARY}", flush=True)


if __name__ == "__main__":
    main()
