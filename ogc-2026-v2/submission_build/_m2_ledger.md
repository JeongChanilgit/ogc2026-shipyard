

# ===== M2 predecessor-density (submission code)  2026-06-24 13:10 =====
# PROBS=[38, 30]  code=_m1base  lam=0.3  unified=True

### prob_38 (w1=13,333)  ORIGINAL(rec)=54,658,258  measure=300 final=900 lam=0.3
  [M2.measure t=  300s] obj=    55,447,756 z1=  4,032 z3= 5,622
  [M2 re-greedy=63,592,472  (선행블록 60개 페널티, tardy 157개 원인추적, z1@measure=4,032)]
  [M2.final t=  600s] obj=    60,481,744 z1=  4,360 z3= 7,807
  [M2.final t=  900s] obj=    59,468,436 z1=  4,284 z3= 7,807
  [M2.final t= 1200s] obj=    59,201,776 z1=  4,264 z3= 7,807
  => prob_38: ORIGINAL=54,658,258  M2=59,201,776  z1=4,264 z3=7,807  gain=-4,543,518  M2<ORIG=False  (1364s)

### prob_30 (w1=13,333)  ORIGINAL(rec)=5,330,072  measure=300 final=900 lam=0.3
  [M2.measure t=  300s] obj=     5,330,072 z1=    360 z3= 2,564
  [M2 re-greedy=6,740,423  (선행블록 31개 페널티, tardy 80개 원인추적, z1@measure=360)]
  [M2.final t=  600s] obj=     6,607,093 z1=    453 z3= 2,818
  [M2.final t=  900s] obj=     6,607,093 z1=    453 z3= 2,818
  [M2.final t= 1200s] obj=     6,607,093 z1=    453 z3= 2,818
  => prob_30: ORIGINAL=5,330,072  M2=6,607,093  z1=453 z3=2,818  gain=-1,277,021  M2<ORIG=False  (949s)

# ===== SUMMARY done=2/2 =====
#   ORIGINAL total = 59,988,330
#   M2       total = 65,808,869   gain = -5,820,539  (0/2 M2 wins)
# ===== COMPLETE 2026-06-24 13:48 =====
