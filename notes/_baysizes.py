import json
for inst in ["prob_1","prob_5","prob_6","prob_8","prob_11","prob_14","prob_19","prob_20"]:
    try:
        p = json.load(open(f"instances/train/{inst}.json", encoding="utf-8"))
    except Exception:
        continue
    nb = len(p["blocks"]); nbay = len(p["bays"])
    # blocks per bay are decided by solver, not fixed; show n_blocks, n_bays, avg
    print(f"{inst:9} blocks={nb:4d} bays={nbay}  ~avg/bay={nb/max(1,nbay):.0f}")
