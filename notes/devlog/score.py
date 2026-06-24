"""Devlog scoring + recording spine for the OGC2026 rebuild.

Reads a capture dir (results/capture/<tag>/<inst>.json with {"met":{...}}),
scores it against the competitor table, prints a per-instance table, and
APPENDS a structured record to notes/devlog/experiments.jsonl plus a
human-readable block to notes/devlog/DEVLOG.md.

This is the per-instance learning log the user asked for: every experiment
self-records here so later runs can diff against earlier ones.

Usage:
  python notes/devlog/score.py --dir results/capture/<tag> --tag <tag> [--env "K=V,..."] [--note "..."]
  python notes/devlog/score.py --dir results/capture/<tagA> --paired results/capture/<tagB> --tag <name>
       (paired = take per-instance MIN(objA,objB) like the adoption gate)
  python notes/devlog/score.py --rebaseline results/_rebaseline600   (run_solver_once schema adapter)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVLOG = ROOT / "notes" / "devlog"
COMP = json.load(open(ROOT / "notes" / "competitor-2026-06-11.json", encoding="utf-8"))["competitor"]
ALL20 = [f"prob_{i}" for i in range(1, 21)]


def load_met_capture(d: Path, inst: str):
    """capture schema: {"met":{wall,feas,z1,z2,z3,obj}}"""
    f = d / f"{inst}.json"
    if not f.exists():
        return None
    try:
        j = json.load(open(f))
        m = j.get("met")
        if m and "obj" in m:
            return {"obj": m["obj"], "z1": m.get("z1"), "z2": m.get("z2"),
                    "z3": m.get("z3"), "wall": m.get("wall"), "feas": m.get("feas")}
    except Exception:
        return None
    return None


def load_met_rebaseline(d: Path, inst: str):
    """run_solver_once schema: pN.json with obj1/obj2/obj3/objective/feasible/elapsed"""
    n = inst.split("_")[1]
    f = d / f"p{n}.json"
    if not f.exists():
        return None
    try:
        j = json.load(open(f))
        return {"obj": j.get("objective"), "z1": j.get("obj1"), "z2": j.get("obj2"),
                "z3": j.get("obj3"), "wall": j.get("elapsed"), "feas": j.get("feasible")}
    except Exception:
        return None


def score(dir_a, paired=None, loader=load_met_capture):
    rows = []
    wins = losses = ties = infeas = missing = 0
    tot_ours = tot_comp = 0.0
    for inst in ALL20:
        ma = loader(dir_a, inst)
        if paired is not None:
            mb = loader(paired, inst)
            if ma and mb and ma["feas"] and mb["feas"]:
                ma = ma if ma["obj"] <= mb["obj"] else mb
            elif mb and (not ma or not ma.get("feas")):
                ma = mb
        comp = COMP[inst]["obj"]
        tot_comp += comp
        if ma is None:
            rows.append((inst, None, comp, "MISS", None)); missing += 1; continue
        if not ma.get("feas"):
            rows.append((inst, ma["obj"], comp, "INFEAS", ma)); infeas += 1; continue
        o = ma["obj"]; tot_ours += o
        if o < comp - 1e-6:
            tag = "WIN"; wins += 1
        elif o > comp + 1e-6:
            tag = "loss"; losses += 1
        else:
            tag = "tie"; ties += 1
        rows.append((inst, o, comp, tag, ma))
    return rows, dict(wins=wins, losses=losses, ties=ties, infeas=infeas, missing=missing,
                      tot_ours=round(tot_ours, 1), tot_comp=round(tot_comp, 1))


def fmt_table(rows):
    lines = [f"{'inst':<9}{'ours_obj':>12}{'comp_obj':>12}{'gap':>12}  {'z1':>5}{'z3':>6}{'wall':>7}  res"]
    for inst, o, c, tag, m in rows:
        if o is None:
            lines.append(f"{inst:<9}{'--':>12}{c:>12.0f}{'--':>12}  {'--':>5}{'--':>6}{'--':>7}  {tag}")
            continue
        gap = o - c
        z1 = m.get("z1"); z3 = m.get("z3"); wall = m.get("wall")
        z1s = f"{z1:.0f}" if z1 is not None else "?"
        z3s = f"{z3:.0f}" if z3 is not None else "?"
        ws = f"{wall:.0f}" if wall is not None else "?"
        mark = "  <<<" if tag == "loss" else (" WIN" if tag == "WIN" else "")
        lines.append(f"{inst:<9}{o:>12.0f}{c:>12.0f}{gap:>+12.0f}  {z1s:>5}{z3s:>6}{ws:>7}  {tag}{mark}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--paired", default=None)
    ap.add_argument("--rebaseline", default=None)
    ap.add_argument("--tag", default="")
    ap.add_argument("--env", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-record", action="store_true")
    a = ap.parse_args()

    if a.rebaseline:
        dir_a = ROOT / a.rebaseline if not a.rebaseline.startswith("/") else Path(a.rebaseline)
        loader = load_met_rebaseline
        tag = a.tag or "rebaseline"
    else:
        dir_a = Path(a.dir)
        if not dir_a.is_absolute():
            dir_a = ROOT / a.dir
        loader = load_met_capture
        tag = a.tag or dir_a.name
    paired = None
    if a.paired:
        paired = Path(a.paired) if Path(a.paired).is_absolute() else ROOT / a.paired

    rows, summ = score(dir_a, paired, loader)
    table = fmt_table(rows)
    hdr = (f"TAG={tag}  WINS={summ['wins']}/20  losses={summ['losses']}  ties={summ['ties']}  "
           f"infeas={summ['infeas']}  miss={summ['missing']}  "
           f"tot_ours={summ['tot_ours']}  tot_comp={summ['tot_comp']}  "
           f"delta={summ['tot_ours']-summ['tot_comp']:+.0f}")
    print(hdr)
    print(table)

    if not a.no_record:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        per = {inst: ({"obj": o, **{k: m.get(k) for k in ("z1", "z2", "z3", "wall", "feas")}}
                      if m else {"obj": None})
               for inst, o, c, tag_, m in rows}
        rec = dict(ts=ts, tag=tag, dir=str(dir_a.relative_to(ROOT)) if dir_a.is_relative_to(ROOT) else str(dir_a),
                   paired=(str(paired) if paired else None), env=a.env, note=a.note,
                   summary=summ, per_instance=per)
        DEVLOG.mkdir(parents=True, exist_ok=True)
        with open(DEVLOG / "experiments.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with open(DEVLOG / "DEVLOG.md", "a", encoding="utf-8") as fh:
            fh.write(f"\n## {ts} — {tag}\n\n")
            if a.note:
                fh.write(f"_{a.note}_\n\n")
            if a.env:
                fh.write(f"`ENV: {a.env}`\n\n")
            fh.write(f"**{hdr}**\n\n```\n{table}\n```\n")
        print(f"\n[recorded] {DEVLOG/'experiments.jsonl'} + DEVLOG.md", file=sys.stderr)


if __name__ == "__main__":
    main()
