# -*- coding: utf-8 -*-
import json, sys
from collections import Counter
inst = sys.argv[1] if len(sys.argv) > 1 else "prob_6"
prob = json.load(open(f"instances/train/{inst}.json", encoding="utf-8"))
blocks = prob["blocks"]
norient = Counter()
dup_tot = uniq_tot = nblk = 0
for b in blocks:
    shp = b["shape"]; norient[len(shp)] += 1; nblk += 1
    sigs = [json.dumps(o, sort_keys=True) for o in shp]
    uniq_tot += len(set(sigs)); dup_tot += len(sigs)
print(f"[{inst}] blocks={nblk}")
print("orientations-per-block histogram:", dict(sorted(norient.items())))
print(f"total orientation slots={dup_tot}  unique-after-dedup={uniq_tot}  "
      f"redundant={dup_tot-uniq_tot} ({100*(dup_tot-uniq_tot)/max(1,dup_tot):.0f}%)")
