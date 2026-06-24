"""Test the hypothesis: residual Z1 (tardiness) is caused by spatial PACKING
(blocks forced to wait for floor space), not by scheduling/assignment.

For each tardy block (exit > due) we look at its admission-wait window
[release, entry). At each integer time in that window we sum the floor-area of
blocks already present in the same bay. If  occupied_area + block_area >
bay_area  (a NECESSARY condition to fit), the block provably could not have
been admitted then -> its wait is area/packing-forced. We report what fraction
of total tardiness is packing-forced, plus bay area-utilisation stats.

Usage: <ogc2025-or-any-python> tools/packing_z1_analysis.py \
   --sols results/z1_exp_B --insts prob_6,prob_11,prob_14,prob_16,prob_20
(sol files: <sols>/sol_<inst>__base.json ; instances: instances/train/<inst>.json)
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def shoelace(poly):
    a = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def footprint_area(shape, orient):
    layers = shape[orient]["layers"]
    return max((shoelace(L) for L in layers), default=0.0)


def analyze(inst_name, sols_dir):
    prob = json.loads((ROOT / "instances" / "train" / f"{inst_name}.json").read_text(encoding="utf-8"))
    sol = json.loads((Path(sols_dir) / f"sol_{inst_name}__base.json").read_text(encoding="utf-8"))["operations"]
    blocks, bays = prob["blocks"], prob["bays"]
    bay_area = [b["width"] * b["height"] for b in bays]

    info = {}
    for t_str, ops in sol.items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            d = info.setdefault(bid, {})
            if op["type"] == "ENTRY":
                d["entry"], d["bay"], d["orient"] = t, op["bay_id"], op["orient_idx"]
            elif op["type"] == "EXIT":
                d["exit"] = t
    area = {bid: footprint_area(blocks[bid]["shape"], d["orient"])
            for bid, d in info.items() if "orient" in d}

    # per-bay present-intervals for fast occupancy
    by_bay = {}
    for bid, d in info.items():
        if "entry" in d and "exit" in d:
            by_bay.setdefault(d["bay"], []).append((d["entry"], d["exit"], bid))

    tot_tard = 0.0
    tard_blocks = 0
    pack_forced_tard = 0.0     # tardiness of blocks whose wait was >=80% area-saturated
    pack_forced_blocks = 0
    nowait_tard = 0.0          # tardy but entered at/near release (lateness not from admission wait)
    # at-release diagnostics for tardy blocks that waited (entry>release)
    rel_counts, rel_utils, delays, empty_wait = [], [], [], 0
    for bid, d in info.items():
        if "entry" not in d or "exit" not in d:
            continue
        blk = blocks[bid]
        tard = max(0, d["exit"] - blk["due_date"])
        if tard <= 0:
            continue
        tot_tard += tard
        tard_blocks += 1
        rel, ent, bay = blk["release_time"], d["entry"], d["bay"]
        if ent <= rel:
            nowait_tard += tard
            continue
        sat = tot = 0
        present = by_bay.get(bay, [])
        ab = area.get(bid, 0.0)
        for t in range(rel, ent):
            occ = sum(area[o] for (e, x, o) in present if e <= t < x and o != bid)
            tot += 1
            if occ + ab > bay_area[bay] + 1e-6:
                sat += 1
        frac = sat / tot if tot else 0.0
        if frac >= 0.80:
            pack_forced_tard += tard
            pack_forced_blocks += 1
        # at-release: how full was the bay the moment this block COULD have entered?
        cnt_rel = sum(1 for (e, x, o) in present if e <= rel < x and o != bid)
        occ_rel = sum(area[o] for (e, x, o) in present if e <= rel < x and o != bid)
        rel_counts.append(cnt_rel)
        rel_utils.append(occ_rel / bay_area[bay] if bay_area[bay] else 0)
        delays.append(ent - rel)
        if cnt_rel == 0:
            empty_wait += 1

    # bay area-utilisation over the horizon (peak & mean occupied/bay_area)
    horizon = max((d["exit"] for d in info.values() if "exit" in d), default=0)
    peak_u, mean_u = [], []
    for j, blist in by_bay.items():
        occs = []
        for t in range(0, horizon + 1):
            occ = sum(area[o] for (e, x, o) in blist if e <= t < x)
            occs.append(occ / bay_area[j] if bay_area[j] else 0)
        if occs:
            peak_u.append(max(occs)); mean_u.append(sum(occs) / len(occs))
    nwait = len(rel_counts)
    return {
        "inst": inst_name, "Z1": tot_tard, "tardy_blocks": tard_blocks,
        "pack_forced_tard": pack_forced_tard, "pack_forced_blocks": pack_forced_blocks,
        "nowait_tard": nowait_tard,
        "pack_pct": (100.0 * pack_forced_tard / tot_tard) if tot_tard else 0.0,
        "peak_util": max(peak_u) if peak_u else 0.0,
        "mean_util": (sum(mean_u) / len(mean_u)) if mean_u else 0.0,
        "waited": nwait,
        "empty_wait_pct": (100.0 * empty_wait / nwait) if nwait else 0.0,
        "avg_rel_cnt": (sum(rel_counts) / nwait) if nwait else 0.0,
        "avg_rel_util": (sum(rel_utils) / nwait) if nwait else 0.0,
        "avg_delay": (sum(delays) / nwait) if nwait else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sols", default="results/z1_exp_B")
    ap.add_argument("--insts", default="prob_6,prob_11,prob_14,prob_16,prob_20")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    rows = [analyze(n.strip(), args.sols) for n in args.insts.split(",")]
    print(f"{'inst':9}{'Z1':>9}{'tardyBlk':>9}{'pack%':>7}{'waited':>7}{'emptyW%':>8}{'relCnt':>7}{'relU':>6}{'avgDelay':>9}")
    for r in rows:
        print(f"{r['inst']:9}{r['Z1']:>9.0f}{r['tardy_blocks']:>9}{r['pack_pct']:>6.0f}%"
              f"{r['waited']:>7}{r['empty_wait_pct']:>7.0f}%{r['avg_rel_cnt']:>7.1f}{r['avg_rel_util']:>6.2f}{r['avg_delay']:>9.1f}")
    print("\npack% = tardy 블록 중 대기구간 80%+ 면적포화였던 블록의 tardiness 비중 (0 = 패킹 원인 아님)")
    print("waited = 진입대기한 tardy 블록 수 · emptyW% = 그중 release 시점 베이가 '완전 비어있던'(블록0개) 비율")
    print("relCnt/relU = release 시점 베이 평균 블록수/면적점유율 · avgDelay = 평균 진입지연(시간)")


if __name__ == "__main__":
    raise SystemExit(main())
