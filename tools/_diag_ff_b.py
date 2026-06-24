from __future__ import annotations
import sys, json, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from fastfloor import build_fast_floor, _min_bbox_area

def parse_solution(sol):
    entry = {}
    exit_t = {}
    for t_str, ops in sol.get("operations", {}).items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            if op.get("type") == "ENTRY" or "x" in op:
                entry[bid] = {"bay_id": op["bay_id"], "entry_time": t}
            else:
                exit_t[bid] = t
    result = {}
    for bid in entry:
        if bid in exit_t:
            result[bid] = dict(entry[bid])
            result[bid]["exit_time"] = exit_t[bid]
    return result

def analyze(name):
    path = ROOT / "instances" / "train" / (name + ".json")
    with open(path) as f:
        prob = json.load(f)
    blocks = prob["blocks"]; bays_data = prob["bays"]
    n = len(blocks); n_bays = len(bays_data)
    total_area = sum(bd["width"]*bd["height"] for bd in bays_data)
    print()
    print("INSTANCE: " + name + "  n=" + str(n) + " n_bays=" + str(n_bays))
    for j, bd in enumerate(bays_data):
        print("  Bay" + str(j) + ": W=" + str(bd["width"]) + " H=" + str(bd["height"]) + " area=" + str(bd["width"]*bd["height"]))
    for j in range(n_bays):
        tp = [i for i,blk in enumerate(blocks)
              if max(range(n_bays), key=lambda k: blk["bay_preferences"][k]) == j]
        asm = sum(_min_bbox_area(blocks[i]) for i in tp)
        ba = bays_data[j]["width"] * bays_data[j]["height"]
        print("  Bay" + str(j) + " top-pref: " + str(len(tp)) + " blks area=" + str(round(asm)) + " bay=" + str(ba) + " " + str(round(asm/ba*100,1)) + "%")
    print("  Running FastFloor tl=20...")
    sol, stats = build_fast_floor(prob, timelimit=20.0, n_workers=4)
    print("  z1=" + str(stats.get("z1")) + " feasible=" + str(stats.get("feasible")) + " reason=" + str(stats.get("reason")))
    print("  target_tard=" + str(stats.get("target_tard")))
    print("  per_bay_z1=" + str(stats.get("per_bay_z1")))
    print("  z1_pre_timing=" + str(stats.get("z1_pre_timing")))
    for j, ft in (stats.get("fixed_time") or {}).items():
        print("  ft bay" + str(j) + ": at_R=" + str(ft["placed_at_R"]) + " delayed=" + str(ft["delayed"]) + " forced=" + str(ft["forced"]) + " tard=" + str(ft["ft_tard"]) + " won=" + str(ft.get("won")))
    print("  xbay_moves=" + str(stats.get("xbay_moves")))
    if sol is None:
        print("  INFEASIBLE"); return
    blk_ops = parse_solution(sol)
    tardy = []
    for bid, op in blk_ops.items():
        blk = blocks[bid]
        D = int(blk["due_date"]); R = int(blk["release_time"]); P = int(blk["processing_time"])
        tard = max(0, op["exit_time"] - D)
        delay = op["entry_time"] - R
        if tard > 0 or delay > 0:
            tardy.append({"bid": bid, "bay": op["bay_id"], "R": R, "D": D, "P": P,
                          "entry": op["entry_time"], "exit": op["exit_time"],
                          "delay": delay, "tard": tard, "area": _min_bbox_area(blk)})
    tardy.sort(key=lambda x: -x["tard"])
    print("  Tardy/delayed blocks (top 30):")
    print("  " + "bid".rjust(6) + "bay".rjust(4) + "R".rjust(6) + "entry".rjust(6) + "delay".rjust(6) + "D".rjust(6) + "exit".rjust(6) + "tard".rjust(6) + "area".rjust(8))
    for tb in tardy[:30]:
        print("  " + str(tb["bid"]).rjust(6) + str(tb["bay"]).rjust(4) + str(tb["R"]).rjust(6) + str(tb["entry"]).rjust(6) + str(tb["delay"]).rjust(6) + str(tb["D"]).rjust(6) + str(tb["exit"]).rjust(6) + str(tb["tard"]).rjust(6) + str(round(tb["area"])).rjust(8))
    by_bay = collections.defaultdict(list)
    for tb in tardy: by_bay[tb["bay"]].append(tb)
    print("  Total z1=" + str(sum(t["tard"] for t in tardy)) + " tardy=" + str(sum(1 for t in tardy if t["tard"]>0)) + " delayed=" + str(sum(1 for t in tardy if t["delay"]>0)))
    for j in sorted(by_bay.keys()):
        print("  Bay" + str(j) + ": z1=" + str(sum(t["tard"] for t in by_bay[j])) + " tardy=" + str(sum(1 for t in by_bay[j] if t["tard"]>0)) + " delayed=" + str(len(by_bay[j])))
    for worst in sorted(by_bay.keys(), key=lambda j: -sum(t["tard"] for t in by_bay[j]))[:2]:
        bids = [bid for bid,op in blk_ops.items() if op["bay_id"] == worst]
        ba = bays_data[worst]["width"] * bays_data[worst]["height"]
        print("  == Bay" + str(worst) + " (" + str(len(bids)) + " blks ba=" + str(ba) + ") ==")
        evts = []
        for b in bids:
            blk = blocks[b]; R = int(blk["release_time"]); P = int(blk["processing_time"])
            a = _min_bbox_area(blk)
            evts.append((R, +a, b)); evts.append((R+P, -a, b))
        evts.sort(); cur = 0.0; act = set(); pt, pa, pb_list = 0, 0.0, []
        for t, da, b in evts:
            if da > 0: act.add(b)
            else: act.discard(b)
            cur += da
            if cur > pa: pa = cur; pt = t; pb_list = list(act)
        print("  Ideal peak: area=" + str(round(pa)) + " @t=" + str(pt) + " (" + str(round(pa/ba*100,1)) + "%) " + str(len(pb_list)) + " blks")
        pk = sorted([(b, _min_bbox_area(blocks[b])) for b in pb_list], key=lambda x: -x[1])
        for b, a in pk[:6]:
            blk = blocks[b]
            print("    blk=" + str(b) + " area=" + str(round(a)) + " R=" + str(blk["release_time"]) + " P=" + str(blk["processing_time"]) + " D=" + str(blk["due_date"]))
        wtb = sorted(by_bay[worst], key=lambda x: -x["tard"])
        print("  Top tardy blocks in Bay" + str(worst) + ":")
        for tb in wtb[:8]:
            print("    bid=" + str(tb["bid"]) + " R=" + str(tb["R"]) + " entry=" + str(tb["entry"]) + " delay=" + str(tb["delay"]) + " D=" + str(tb["D"]) + " tard=" + str(tb["tard"]) + " area=" + str(round(tb["area"])))
        tba = sum(_min_bbox_area(blocks[b]) for b in bids)
        print("  Total blk area in bay: " + str(round(tba)) + " vs ba=" + str(ba) + " (" + str(round(tba/ba*100,1)) + "%)")
        for tb_bid in [t["bid"] for t in wtb if t["tard"] > 0][:3]:
            op = blk_ops[tb_bid]; te = op["entry_time"]; tx = op["exit_time"]
            ov = [(b2, blk_ops[b2]["entry_time"], blk_ops[b2]["exit_time"], _min_bbox_area(blocks[b2]))
                  for b2 in bids if b2 != tb_bid and blk_ops[b2]["entry_time"] < tx and blk_ops[b2]["exit_time"] > te]
            print("  blk" + str(tb_bid) + "(tard=" + str(tx-blocks[tb_bid]["due_date"]) + ") R=" + str(blocks[tb_bid]["release_time"]) + " entry=" + str(te) + ": " + str(len(ov)) + " overlapping")
            for b2, a2, e2, ar in sorted(ov, key=lambda x: -x[3])[:4]:
                print("    ov blk=" + str(b2) + " entry=" + str(a2) + " exit=" + str(e2) + " area=" + str(round(ar)))

if __name__ == "__main__":
    for name in ["prob_14", "prob_20"]:
        try:
            analyze(name)
        except Exception as e:
            import traceback
            print("ERROR " + name + ": " + str(e))
            traceback.print_exc()
