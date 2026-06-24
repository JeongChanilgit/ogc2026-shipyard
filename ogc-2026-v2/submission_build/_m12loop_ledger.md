

# ===== M1 2-LOOP vs ORIGINAL (submission code)  2026-06-24 11:36 =====
# PROBS=[38, 30]  code=_m1base  unified=True

### prob_38 (w1=13,333)  measure=300 final=900 total_txyo=1200 lam=0.2
  [ORIG greedy=62,162,996]
  [ORIG t=  300s] obj=    56,044,890 z1=  4,074 z3= 5,746
  [ORIG t=  600s] obj=    55,004,916 z1=  3,996 z3= 5,746
  [ORIG t=  900s] obj=    54,711,590 z1=  3,974 z3= 5,746
  [ORIG t= 1200s] obj=    54,658,258 z1=  3,970 z3= 5,746
  ORIGINAL final = 54,658,258 z1=3,970 (1293s)
  [2L.measure t=  300s] obj=    56,836,845 z1=  4,131 z3= 5,852
  [2L re-greedy=63,571,917  (fed back 162 tardy from t=300 z1=4,131)]
  [2L.final t=  600s] obj=    59,095,508 z1=  4,262 z3= 7,544
  [2L.final t=  900s] obj=    58,258,269 z1=  4,203 z3= 7,374
  [2L.final t= 1200s] obj=    57,162,888 z1=  4,124 z3= 7,234
  2LOOP final = 57,162,888 z1=4,124 (1371s)
  => prob_38: ORIGINAL=54,658,258  2LOOP=57,162,888  gain=-2,504,630  2LOOP<ORIG=False

### prob_30 (w1=13,333)  measure=300 final=900 total_txyo=1200 lam=0.2
  [ORIG greedy=5,610,065]
  [ORIG t=  300s] obj=     5,330,072 z1=    360 z3= 2,564
  [ORIG t=  600s] obj=     5,330,072 z1=    360 z3= 2,564
  [ORIG t=  900s] obj=     5,330,072 z1=    360 z3= 2,564
  [ORIG t= 1200s] obj=     5,330,072 z1=    360 z3= 2,564
  ORIGINAL final = 5,330,072 z1=360 (810s)
  [2L.measure t=  300s] obj=     5,343,405 z1=    361 z3= 2,564
  [2L re-greedy=6,780,516  (fed back 81 tardy from t=300 z1=361)]
  [2L.final t=  600s] obj=     6,060,534 z1=    418 z3= 2,384
  [2L.final t=  900s] obj=     6,007,202 z1=    414 z3= 2,384
  [2L.final t= 1200s] obj=     6,007,202 z1=    414 z3= 2,384
  2LOOP final = 6,007,202 z1=414 (1081s)
  => prob_30: ORIGINAL=5,330,072  2LOOP=6,007,202  gain=-677,130  2LOOP<ORIG=False

# ===== SUMMARY done=2/2 =====
#   ORIGINAL total = 59,988,330
#   2LOOP    total = 63,170,090   gain = -3,181,760
# ===== COMPLETE 2026-06-24 12:52 =====


# ===== M1 2-LOOP vs ORIGINAL (submission code)  2026-06-24 12:54 =====
# PROBS=[38]  code=_m1base  unified=True

### prob_38 (w1=13,333)  measure=300 final=2700 total_txyo=3000 lam=0.2
  [ORIG = recorded 54,658,258 (skipped re-run)]
  [2L.measure t=  300s] obj=    55,179,978 z1=  4,010 z3= 5,708
  [2L re-greedy=64,042,924  (fed back 155 tardy from t=300 z1=4,010)]
