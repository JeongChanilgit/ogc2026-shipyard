"""Final summary: bpass scope vs full-reassignment z3 recovery."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

probs_z3h = [36, 24, 34, 31, 28, 21, 35]

res = json.load(open("z3_headroom_results.json"))
res_map = {r["prob"]: r for r in res}

z3_split = {
    36: {"tw": 2077, "nw": 5327, "w3": 13},
    24: {"tw": 162,  "nw": 832,  "w3": 300},
    34: {"tw": 127,  "nw": 567,  "w3": 533},
    31: {"tw": 4013, "nw": 5900, "w3": 267},
    28: {"tw": 605,  "nw": 1803, "w3": 300},
    21: {"tw": 886,  "nw": 1829, "w3": 150},
    35: {"tw": 929,  "nw": 2254, "w3": 150},
}

print("=== z3 RECOVERY POTENTIAL SUMMARY (z3-heavy set, set2) ===")
print()
hdr = "p    | w3*z3_cur | rec_AN   | w3*recAN | nontardy% | w3*nontardy | w3*tardy"
print(hdr)
print("-" * 80)

sum_w3z3 = 0.0
sum_rec_an = 0.0
sum_nontardy = 0.0
sum_tardy = 0.0

for p in probs_z3h:
    r = res_map[p]
    sp = z3_split[p]
    w3 = sp["w3"]
    tot = sp["tw"] + sp["nw"]
    nt_pct = 100 * sp["nw"] / tot if tot else 0
    w3nt = w3 * sp["nw"]
    w3t = w3 * sp["tw"]
    rec_an = r["recover_an"] or 0.0
    w3_rec = r["w3_recover_an"] or 0.0

    sum_w3z3 += r["w3z3_cur"]
    sum_rec_an += w3_rec
    sum_nontardy += w3nt
    sum_tardy += w3t

    print("%-4d | %9.0f | %8.0f | %8.0f | %8.0f%% | %11.0f | %9.0f" %
          (p, r["w3z3_cur"], rec_an, w3_rec, nt_pct, w3nt, w3t))

print("-" * 80)
print("TOT  | %9.0f |          | %8.0f |           | %11.0f | %9.0f" %
      (sum_w3z3, sum_rec_an, sum_nontardy, sum_tardy))

print()
print("KEY METRICS:")
print("  Total w3*z3 (z3-heavy set2 x7):     %11.0f" % sum_w3z3)
print("  Area-neutral recoverable (z1-safe):  %11.0f  (%.0f%% of w3*z3)" %
      (sum_rec_an, 100 * sum_rec_an / sum_w3z3))
print("  of which non-tardy wrong-bay:         %11.0f  (%.0f%% of w3*z3)" %
      (sum_nontardy, 100 * sum_nontardy / sum_w3z3))
print("  of which tardy wrong-bay (bpass):     %11.0f  (%.0f%% of w3*z3)" %
      (sum_tardy, 100 * sum_tardy / sum_w3z3))
print()
print("INTERPRETATION:")
print("  bpass targets ONLY tardy+wrong blocks = w3*tardy_wrong = %.0f (%.0f%%)" %
      (sum_tardy, 100 * sum_tardy / sum_w3z3))
print("  NON-tardy wrong-bay blocks are the main gap (%.0f%% of w3*z3)" %
      (100 * sum_nontardy / sum_w3z3))
print("  slack_movable=0/wrg for most (co-presence > 3) => can't just swap one block")
print("  => FULL GLOBAL REASSIGNMENT needed to capture non-tardy z3")
print()

# Full set2 (all 20 instances)
all_res = {r["prob"]: r for r in res}
set2_total_obj = None  # not measured here; reference from memory: 165.9M
set2_w3z3_measured = sum(r["w3z3_cur"] for r in res if r["prob"] in range(21, 41))
print("set2 w3*z3 (11 instances measured): %.0f" % set2_w3z3_measured)
print("set2 total obj reference: ~165.9M")
set2_ref_obj = 165_900_000
print("  => w3*z3 / set2_obj ~ %.1f%%" % (100 * set2_w3z3_measured / set2_ref_obj))
print()
# Area-neutral recovery for all measured
sum_rec_an_all = sum((r["w3_recover_an"] or 0) for r in res)
print("Area-neutral recovery (all 11 measured): %.0f" % sum_rec_an_all)
print("  => %.1f%% of set2_obj" % (100 * sum_rec_an_all / set2_ref_obj))
