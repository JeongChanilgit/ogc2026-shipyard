"""Run the crane-aware fast floor (src/fastfloor.py) on train instances.

Usage:
    conda run -n ogc2025 python tools/run_fastfloor.py \
        [--dir instances/train] [--timelimit 20] [--probs prob_1,prob_13] \
        [--out results/fastfloor_v1.json]

Prints one row per instance (with the 2026-06-11 competitor reference), then a
summary line: #z1=0 / #finished within the timelimit / mean wall.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def _load_competitor() -> dict:
    """notes/competitor-2026-06-11.json -> {prob: {obj,z1,z2_unfloored,z3,wall_s}}."""
    p = ROOT / "notes" / "competitor-2026-06-11.json"
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("competitor", {})
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast-floor smoke runner")
    ap.add_argument("--dir", default="instances/train")
    ap.add_argument("--timelimit", type=float, default=20.0)
    ap.add_argument("--probs", default="",
                    help="comma list, e.g. prob_1,prob_13 (default: all in --dir)")
    ap.add_argument("--out", default="results/fastfloor_v1.json")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    inst_dir = (ROOT / args.dir) if not Path(args.dir).is_absolute() else Path(args.dir)
    if args.probs:
        names = [s.strip() for s in args.probs.split(",") if s.strip()]
        paths = [inst_dir / f"{nm}.json" for nm in names]
    else:
        paths = sorted(inst_dir.glob("prob_*.json"),
                       key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"[error] missing instances: {[str(m) for m in missing]}")
        return 2

    from fastfloor import build_fast_floor

    comp = _load_competitor()
    rows = []
    hdr = (f"{'prob':<9}{'n':>5}{'bays':>5}{'wall':>7}{'z1':>8}{'z2':>9}"
           f"{'z3':>7}{'obj':>11}{'feas':>6} | "
           f"{'c_z1':>6}{'c_z3':>7}{'c_obj':>11}{'c_wall':>7}")
    print(hdr, flush=True)
    for p in paths:
        with open(p, encoding="utf-8") as f:
            prob_info = json.load(f)
        prob_info.setdefault("name", p.stem)
        t0 = time.monotonic()
        try:
            sol, st = build_fast_floor(prob_info, timelimit=args.timelimit,
                                       n_workers=args.workers)
        except Exception as e:  # never let one instance kill the batch
            sol, st = None, {"reason": f"crash: {e!r}", "feasible": False,
                             "n": len(prob_info.get("blocks", [])),
                             "n_bays": len(prob_info.get("bays", []))}
        wall = time.monotonic() - t0
        st["wall_s"] = round(wall, 2)
        c = comp.get(p.stem, {})
        z1 = st.get("z1"); z2 = st.get("z2"); z3 = st.get("z3")
        obj = st.get("obj")
        feas = "Y" if st.get("feasible") else "N"
        fmt = lambda v, w: f"{v:>{w}.1f}" if isinstance(v, float) else f"{str(v):>{w}}"
        print(f"{p.stem:<9}{st.get('n', '?'):>5}{st.get('n_bays', '?'):>5}"
              f"{wall:>7.1f}{fmt(z1, 8)}{fmt(z2, 9)}{fmt(z3, 7)}{fmt(obj, 11)}"
              f"{feas:>6} | {fmt(c.get('z1'), 6)}{fmt(c.get('z3'), 7)}"
              f"{fmt(c.get('obj'), 11)}{fmt(c.get('wall_s'), 7)}", flush=True)
        if not st.get("feasible"):
            print(f"  -> reason={st.get('reason')} stats={ {k: v for k, v in st.items() if k != 'per_bay_z1'} }",
                  flush=True)
        rows.append({"prob": p.stem, "stats": st, "competitor": c})

    n_run = len(rows)
    n_z1_0 = sum(1 for r in rows
                 if r["stats"].get("feasible") and r["stats"].get("z1", 1) == 0)
    n_in_tl = sum(1 for r in rows if r["stats"].get("wall_s", 1e9) <= args.timelimit)
    avg_wall = (sum(r["stats"].get("wall_s", 0.0) for r in rows) / n_run) if n_run else 0.0
    print(f"\nsummary: z1=0 {n_z1_0}/{n_run} | within {args.timelimit:.0f}s "
          f"{n_in_tl}/{n_run} | avg wall {avg_wall:.1f}s", flush=True)

    out_path = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"timelimit": args.timelimit, "rows": rows,
                   "summary": {"z1_zero": n_z1_0, "within_tl": n_in_tl,
                               "avg_wall": round(avg_wall, 2), "n": n_run}},
                  f, indent=2)
    print(f"saved -> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
