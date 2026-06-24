"""Quick check: wrong-bay blocks split by tardy/non-tardy (bpass scope check)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import utils as _utils

target_probs = [36, 24, 34, 31, 28, 21, 35, 22, 29, 38, 27]
z3_heavy = {36, 24, 34, 31, 28, 21, 35}
zero_z1 = {22, 29}

print("%-4s | %8s | %10s | %13s | %5s" % ("p", "wrg_tot", "wrg+tardy", "wrg+nontardy", "tag"))
print("-" * 55)
for p in target_probs:
    data = json.load(open(f"C:/claude-develop/OGC2026/instances/train/prob_{p}.json", encoding="utf-8"))
    sol = json.load(open(f"real_prob_{p}.json", encoding="utf-8"))
    blocks = data["blocks"]
    m = len(data["bays"])

    cur_bay = {}
    cur_entry = {}
    cur_exit = {}
    for t_str, ops in sol["operations"].items():
        t = int(t_str)
        for op in ops:
            bid = int(op["block_id"])
            if op["type"] == "ENTRY":
                cur_bay[bid] = int(op["bay_id"])
                cur_entry[bid] = t
            elif op["type"] == "EXIT":
                cur_exit[bid] = t

    wrong_tardy = 0
    wrong_nontardy = 0
    for bid, bj in cur_bay.items():
        blk = blocks[bid]
        pref = max(range(m), key=lambda j: blk["bay_preferences"][j])
        exit_t = cur_exit.get(bid, cur_entry.get(bid, 0) + blk["processing_time"])
        tardy = max(0, exit_t - blk["due_date"]) > 0
        is_wrong = (bj != pref)
        if is_wrong:
            if tardy:
                wrong_tardy += 1
            else:
                wrong_nontardy += 1

    total_wrong = wrong_tardy + wrong_nontardy
    tag = "z3H" if p in z3_heavy else ("z1=0" if p in zero_z1 else "z1H")
    print("%-4d | %8d | %10d | %13d | %5s" % (p, total_wrong, wrong_tardy, wrong_nontardy, tag))
