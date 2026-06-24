import json, os, sys, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def feas(prob, sol):
    from utils import check_feasibility
    r = check_feasibility(prob, sol)
    return r

def run_one(probpath, base_builder_name, base_tl, lns_tl, label):
    prob = load(probpath)
    import lns
    print(f"\n===== {label}  ({os.path.basename(probpath)}) =====", flush=True)
    # build base
    t0 = time.monotonic()
    if base_builder_name == "box":
        os.environ["OGC_BOXDECOMP"] = "1"
        os.environ["OGC_FEASSPILL"] = "0"
        import boxsolver
        base = boxsolver.algorithm(prob, base_tl)
    else:
        import myalgorithm
        base = myalgorithm._legacy_algorithm(prob, base_tl)
    base_wall = time.monotonic() - t0
    rb = feas(prob, base)
    print(f"BASE  feasible={rb.get('feasible')} obj={rb.get('objective')} "
          f"z1={rb.get('obj1')} z2={rb.get('obj2')} z3={rb.get('obj3')} wall={base_wall:.1f}s", flush=True)
    if not rb.get("feasible"):
        print("BASE infeasible -> abort", flush=True)
        return
    # telemetry log
    logp = os.path.join(os.path.dirname(__file__), f"_lns_tel_{label}.jsonl")
    try:
        if os.path.exists(logp): os.remove(logp)
    except Exception: pass
    os.environ["OGC_PERBAY_LOG"] = logp
    # run LNS
    t1 = time.monotonic()
    out = lns.improve(prob, base, lns_tl)
    lns_wall = time.monotonic() - t1
    ro = feas(prob, out)
    identity = out is base
    print(f"LNS   feasible={ro.get('feasible')} obj={ro.get('objective')} "
          f"z1={ro.get('obj1')} z2={ro.get('obj2')} z3={ro.get('obj3')} wall={lns_wall:.1f}s "
          f"identity={identity}", flush=True)
    # parse telemetry
    tot_iters = tot_accepts = 0
    perbay = []
    try:
        with open(logp, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("event") != "lns_improve":
                    continue
                tot_iters += rec.get("iters", 0)
                tot_accepts += rec.get("accepts", 0)
                for b in rec.get("bays", []):
                    perbay.append(b)
    except Exception as e:
        print("tel parse err", e, flush=True)
    print(f"LNS   total_iters={tot_iters} total_accepts={tot_accepts}", flush=True)
    for b in sorted(perbay, key=lambda x: -x.get("cur_tard", 0))[:12]:
        print(f"   bay {b['bay']:>3} n={b['n_blocks']:>4} cur_tard={b['cur_tard']:.0f} "
              f"new_tard={b['new_tard']} status={b['status']} iters={b.get('iters')} "
              f"accepts={b.get('accepts')} wall={b['wall']:.1f}s err={b.get('err')}", flush=True)
    # verdict for z1
    if ro.get("feasible"):
        print(f">>> z1: base {rb.get('obj1'):.0f} -> LNS {ro.get('obj1'):.0f}  "
              f"(delta {ro.get('obj1')-rb.get('obj1'):.0f})", flush=True)
        print(f">>> obj: base {rb.get('objective'):.0f} -> LNS {ro.get('objective'):.0f}  "
              f"(delta {ro.get('objective')-rb.get('objective'):.0f})", flush=True)

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    inst = os.path.join(os.path.dirname(__file__), "..", "instances", "train")
    if which in ("all", "p38"):
        run_one(os.path.join(inst, "prob_38.json"), "box", 120.0, 600.0, "p38_box_lns600")
    if which in ("all", "p14"):
        run_one(os.path.join(inst, "prob_14.json"), "legacy", 90.0, 120.0, "p14_legacy_lns120")
