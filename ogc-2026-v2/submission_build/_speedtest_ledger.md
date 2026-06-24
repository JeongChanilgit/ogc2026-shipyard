

# ===== AABB on/off (submission config: moveall on, x,y,o, cap1)  2026-06-24 21:00 =====
# PROBS=[38, 30]  code=v7

### prob_38 (w1=13,333)  txyo=600s/arm
  [greedy start obj=61,389,682]
  [AABBoff t=  300s] obj=    55,297,497 z1=  4,011 z3= 6,057
  [AABBoff t=  600s] obj=    54,564,182 z1=  3,956 z3= 6,057
  AABBoff final = 54,564,182 z1=3,956 (599s)
  [AABBon  t=  300s] obj=    55,351,237 z1=  4,017 z3= 5,971
  [AABBon  t=  600s] obj=    54,809,497 z1=  3,975 z3= 6,032
  AABBon  final = 54,809,497 z1=3,975 (599s)
  => prob_38: AABBoff=54,564,182  AABBon=54,809,497  diff=-245,315  (AABB는 동일출력 기대 -- 차이=속도효과+노이즈)

### prob_30 (w1=13,333)  txyo=600s/arm
  [greedy start obj=5,610,065]
