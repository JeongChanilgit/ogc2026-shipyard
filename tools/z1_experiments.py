"""Z1 (tardiness) reduction experiment driver.

Runs a matrix of {config x instance} for our solver, each config = a set of
OGC_* env overrides, and records objective + Z1/Z2/Z3 + feasibility + wall.
Sequential (one solver at a time) so wall-times are honest (mirrors eval server).

Run UNDER the ogc2025 python so children inherit the right interpreter:
  <ogc2025-python> tools/z1_experiments.py --timelimit 60 --outdir results/z1_exp_A \
      --instances prob_1,prob_6,prob_11,prob_16

Output: <outdir>/results.json  +  a printed config x instance table (Z1 and objective).
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
RUNNER = ROOT / "tools" / "run_solver_once.py"

# config name -> env overrides (empty = reverted default baseline)
CONFIGS = {
    "base":      {},
    "opw_618":   {"OGC_OP_WEIGHTS": "0.6,0.6,1.8"},          # worst-tardiness destroy up
    "sa25":      {"OGC_SA_TEMP": "0.25"},                     # hotter SA -> escape tight packs
    "tardy1st":  {"OGC_SEED_PRIORITY": "tardy,pref,balanced,cpsat"},
    "combo":     {"OGC_OP_WEIGHTS": "0.6,0.6,1.8",
                  "OGC_SEED_PRIORITY": "tardy,pref,balanced,cpsat"},
    # structural (quantum-jump) configs
    "m4cut":     {"OGC_M4_CUT": "1"},                        # #1 conflict-cut (existing flag)
    "dueforce":  {"OGC_DUE_FORCE": "1"},                     # #3 due-aware force-place (guard lift)
    "df_m4":     {"OGC_DUE_FORCE": "1", "OGC_M4_CUT": "1"},  # #1 + #3
    "coexit":    {"OGC_CRANE_COEXIT": "1"},                  # co-exit crane bug fix (decoder vs official checker)
    "cx_cap150": {"OGC_CRANE_COEXIT": "1", "OGC_CAND_CAP": "150"},  # fix + candidate pruning (faster decode)
    "cx_cap80":  {"OGC_CRANE_COEXIT": "1", "OGC_CAND_CAP": "80"},
    # adaptive cap: cap ONLY bays with >=45 blocks; small bays unlimited
    "adapt80":   {"OGC_CRANE_COEXIT": "1", "OGC_CAND_CAP": "80",  "OGC_CAND_CAP_MIN": "45"},
    "adapt120":  {"OGC_CRANE_COEXIT": "1", "OGC_CAND_CAP": "120", "OGC_CAND_CAP_MIN": "45"},
    "adapt_m55": {"OGC_CRANE_COEXIT": "1", "OGC_CAND_CAP": "120", "OGC_CAND_CAP_MIN": "55"},
    "adapt_m60": {"OGC_CRANE_COEXIT": "1", "OGC_CAND_CAP": "120", "OGC_CAND_CAP_MIN": "60"},
}


def _last_json(text):
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


def run_one(inst: Path, cfg_name, env_over, timelimit, outdir):
    score = outdir / f"score_{inst.stem}__{cfg_name}.json"
    sol = outdir / f"sol_{inst.stem}__{cfg_name}.json"
    env = dict(os.environ)
    env.update(env_over)
    cmd = [PY, str(RUNNER), str(inst), "--solver", "our",
           "--timelimit", str(timelimit), "--out", str(score), "--save-sol", str(sol)]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timelimit * 4 + 60, env=env)
        wall = time.monotonic() - t0
        res = None
        if score.exists():
            try:
                res = json.loads(score.read_text(encoding="utf-8"))
            except Exception:
                res = None
        if res is None:
            res = _last_json(p.stdout)
        if res is None:
            res = {"feasible": False, "error": f"no-json rc={p.returncode} {p.stderr[-200:]}"}
        res["wall"] = round(wall, 2)
        res["deadline_fail"] = bool(wall > timelimit)
    except subprocess.TimeoutExpired:
        res = {"feasible": False, "error": "HARD_TIMEOUT",
               "wall": round(time.monotonic() - t0, 2), "deadline_fail": True}
    ok = res.get("feasible") and not res.get("deadline_fail")
    print(f"  [{'OK ' if ok else 'FAIL'}] {inst.stem:9} {cfg_name:10} "
          f"obj={res.get('objective')} Z1={res.get('obj1')} wall={res.get('wall')}s", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timelimit", type=float, default=60.0)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--instances", default="prob_1,prob_6,prob_11,prob_16",
                    help="comma list of instance stems under instances/train/")
    ap.add_argument("--configs", default=None, help="comma list of config names (default all)")
    args = ap.parse_args()

    outdir = ROOT / args.outdir if not Path(args.outdir).is_absolute() else Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    insts = [ROOT / "instances" / "train" / f"{s.strip()}.json" for s in args.instances.split(",")]
    cfgs = [c.strip() for c in args.configs.split(",")] if args.configs else list(CONFIGS)

    records = []
    print(f"[z1] {len(insts)} instances x {len(cfgs)} configs  tl={args.timelimit}s")
    for cfg in cfgs:
        print(f"[z1] === config {cfg} :: {CONFIGS.get(cfg, {})} ===")
        for inst in insts:
            r = run_one(inst, cfg, CONFIGS.get(cfg, {}), args.timelimit, outdir)
            r["instance"], r["config"] = inst.stem, cfg
            records.append(r)

    (outdir / "results.json").write_text(
        json.dumps({"timelimit": args.timelimit, "configs": cfgs,
                    "records": records}, indent=2, default=str), encoding="utf-8")

    # quick table: Z1 per (instance, config) and objective
    insts_s = [i.stem for i in insts]
    def get(inst, cfg, key):
        for r in records:
            if r["instance"] == inst and r["config"] == cfg:
                ok = r.get("feasible") and not r.get("deadline_fail")
                if not ok:
                    return None
                return r.get(key)
        return None
    def fmt(v, comma=False):
        if v is None:
            return "FAIL"
        return f"{v:,.0f}" if comma else str(int(v))
    print("\n=== Z1 (tardiness) by config ===")
    print("inst     " + "".join(f"{c:>14}" for c in cfgs))
    for inst in insts_s:
        cells = [f"{fmt(get(inst, c, 'obj1')):>14}" for c in cfgs]
        print(f"{inst:9}" + "".join(cells))
    print("\n=== objective by config ===")
    print("inst     " + "".join(f"{c:>14}" for c in cfgs))
    for inst in insts_s:
        cells = [f"{fmt(get(inst, c, 'objective'), comma=True):>14}" for c in cfgs]
        print(f"{inst:9}" + "".join(cells))
    out_path = outdir / "results.json"
    print(f"\n[z1] {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
