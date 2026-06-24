"""Standalone box-decomp eval: run boxsolver.algorithm(prob, TL) alone per set2
instance, to measure box's FULL-budget potential (in production box only gets
~36s; here it gets the full TL). Combine with gassign@TL for the parallel best-of
ceiling. Run: env python notes/_box_eval.py --instances SET2 --timelimit 120
"""
import sys, os, json, time, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, "src")


def resolve(spec):
    spec = (spec or "SET2").strip().upper()
    if spec == "SET1": return [f"prob_{i}" for i in range(1, 21)]
    if spec == "SET2": return [f"prob_{i}" for i in range(21, 41)]
    if spec == "ALL40": return [f"prob_{i}" for i in range(1, 41)]
    out = []
    for tok in spec.split(","):
        tok = tok.strip().lower()
        if not tok: continue
        if tok.startswith("prob_"): out.append(tok)
        elif tok.isdigit(): out.append(f"prob_{tok}")
        else: out.append(tok)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="SET2")
    ap.add_argument("--timelimit", type=float, default=120.0)
    ap.add_argument("--out", default="notes/box-eval")
    args = ap.parse_args()

    os.environ["OGC_BOXDECOMP"] = "1"
    os.environ["OGC_FEASSPILL"] = "0"
    import boxsolver as _bs
    from utils import check_feasibility

    insts = resolve(args.instances)
    print(f"[box-eval] {len(insts)} instances TL={args.timelimit}", flush=True)
    recs = []
    for i, name in enumerate(insts, 1):
        path = os.path.join("instances", "train", name + ".json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                prob = json.load(f)
        except Exception as e:
            print(f"[box-eval] ({i}/{len(insts)}) {name}: LOAD FAIL {e}", flush=True)
            continue
        print(f"[box-eval] ({i}/{len(insts)}) {name}: box.algorithm TL={args.timelimit}s...", flush=True)
        t0 = time.monotonic()
        status = "OK"; obj = z1 = z2 = z3 = None; feas = False
        try:
            sol = _bs.algorithm(prob, args.timelimit)
            wall = time.monotonic() - t0
            c = check_feasibility(prob, sol)
            feas = bool(c.get("feasible"))
            obj = c.get("objective"); z1 = c.get("obj1"); z2 = c.get("obj2"); z3 = c.get("obj3")
        except Exception as e:
            wall = time.monotonic() - t0
            status = f"CRASH:{type(e).__name__}"
        print(f"[box-eval]     {name}: {status} feas={feas} obj={obj} z1={z1} wall={wall:.1f}s", flush=True)
        recs.append({"instance": name, "status": status, "feasible": feas,
                     "box_obj": obj, "z1": z1, "z2": z2, "z3": z3, "wall": wall})
    with open(args.out + ".json", "w", encoding="utf-8") as f:
        json.dump({"timelimit": args.timelimit, "instances": recs}, f, indent=2)
    print(f"[box-eval] wrote {args.out}.json", flush=True)


if __name__ == "__main__":
    main()
