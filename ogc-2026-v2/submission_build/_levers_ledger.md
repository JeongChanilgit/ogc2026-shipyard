# Repack-lever experiment campaign — 2026-06-24 PM/evening

User directive: "여기 개선방안들 다 실험해봐 … 다 하고 다 테스트 해봐" — implement & test
ALL of the P1–P4 levers from the improvement plan, single config, judge by full-set
ALL40 total obj + never−1.  Gates default OFF (production unchanged).

Code: `v7/v3pp/crane_cpsat.py` (all levers gated env knobs) + `v7/postproc.py` (OGC_PP_K).
env python: `C:/Users/peter/anaconda3/envs/ogc2025/python.exe` (conda run 금지).

## Lever inventory (all gated, default OFF = production)
| id | knob | what | status |
|---|---|---|---|
| P1① | `OGC_PP_ACTIVE_CAP=N` | cap #active(multi-cand) blocks, worst-tardy+blockers first | BUILT |
| P1② | `OGC_PP_K=N` (postproc) / n_xcand | candidate count per block (K²→disjunctions) | EXISTS |
| P1③ | `OGC_PP_MEMO=1` | memoize (bay,a,pose_a,b,pose_b)→5 bools across passes | BUILT, output-invariant ✓ |
| P3 | `OGC_PP_ACTIVE_MODE=blocker` | active = ACTUAL current blockers (path-aware check_*) | BUILT |
| P2① | `OGC_XSMART=1` | x-anchors snapped to neighbour edges (boolean-flip) | EXISTS |
| P2② | `OGC_PP_BLPROBE=N` | tardy-only low-conflict (x,y) diagonal seeds (bbox-overlap score) | BUILT |
| P4b | `OGC_PP_TIGHTEN=1` | per-block entry ub = max(R,cur_entry,due)+maxP (domain shrink) | BUILT |
| P4a | (z2-proxy) | peak co-presence penalty | DEFERRED (reasoned, see below) |
| P1④ | `OGC_PRECOMP_BITMASK` | cell-footprint bitset prefilter | **FALSIFIED** (unsafe) |

## Findings

### P1④ bitmask — FALSIFIED (unsafe, drops 855 real constraints)  [_bmbench.log]
prob_38 bay2 (107 blk), n_stored ground-truth(no filter)=20,880; AABB=20,880 (safe);
**AABB+BM=20,025, BMonly=20,025** → bitmask drops 855 constraints (both wto cases).
Root cause: ENTRY/EXIT sweep a PATH beyond the final footprint (interlock: bboxes
overlap, final cells disjoint, but the entry path collides). bitmask sees only final
cells → unsafe. Handoff expected "출력동일" — bench falsifies. **NOT added.** AABB stays
(safe, −19% precompute, identical output).

### Smoke test (prob_38 bay2, single pass, ts=6s)  [_levertest.log]
- **P1③ memo OUTPUT-INVARIANCE: PASS** — pair_bools off==on==hit (20,880 each). SAFE
  (unlike bitmask). Single-pass shows no speedup (cold cache); benefit is multi-pass.
- **P1① cap20 = standout**: cands 619→201, stored 20,880→**2,636 (−87%)**, precompute
  5.00→**0.77s (−85%)**, new_z1 1,944→1,885 (better!). cap40: stored 5,500, z1 1,923.
  Smaller model solved better AND faster in same 6s CP-SAT. Hits the 72% directly.
- **P3 blocker = neutral here** (saturated bay: all 107 are real blockers → active
  stays 107, no shrink, + probe cost). May help sparse bays only.
- **P2① xsmart = neutral** (stored 20,592, no z1 gain single-pass).

## In progress
- **Convergence A/B screen** (`_levab.py`, 300s/arm, shared greedy sol0):
  prob_38 (cores0-3) + prob_30 (cores4-7) PARALLEL. arms: prod / cap20 / cap40 /
  cap20mem / K3. Question: cheaper pass → more rounds → lower final obj?  → `_levab_{38,30}.log`

## Convergence screen RESULTS (300s/arm, shared greedy)  [_levab_{38,30}.log]
INSTANCE-DEPENDENT — cap wins BIG/round-starved, loses small/converged:

| arm | prob_38 (107-blk bays) | prob_30 (converges@t200) |
|---|---|---|
| prod     | 57,976,434 (base) | **5,330,072 (BEST)** |
| **cap20**| **53,443,214 (−4.53M!)** | 5,469,056 (+139K worse) |
| cap20mem | 55,203,170 (−2.77M) | 5,495,722 (+166K worse) |
| cap40    | 56,629,801 (−1.35M) | 5,455,723 (+126K worse) |
| K3       | (running)         | 5,516,734 (+187K worse) |

- prob_38: prod ROUND-STARVED (107-blk pass ~15s, full 20K-disjunction model times
  out under-solved @40s/pass) → cap20's 2.6K-disjunction model solves OPTIMAL + fits
  many more rounds → −4.53M / −7.8% WIN. Single-pass intuition CONFIRMED at scale.
- prob_30: prod CONVERGES by t=200 (not round-starved) → cap's reach loss (only 20
  movable blocks) dominates → +139K LOSS. memo output-invariance reconfirmed
  (cap20==cap20mem first point 5,495,722).
- NET: prob_38 win (4.5M) ≫ prob_30 loss (139K), ~30×. set2 mostly big like prob_38.
  → decide on FULL-SET ALL40 total obj @ operational TL=120 (where leftover budget is
  short → round-starvation worse → cap likely helps even more). User rule: single
  config, no set-branch. cap is solve-time-adaptive-friendly IF round-starvation is the
  trigger (big bays under tight budget) — but a FIXED cap hurts converged instances.

## ⚠ FULL-SET PAIRED A/B @TL=120 — INVALID (base-solver variance artifact)  [_levfull_*.json]
prod TOTAL=184,503,128 (set1 1.44M, set2 183.1M) feasible 40/40 never−1.
cap20 TOTAL=644,355,746 (set1 1.64M, set2 **642.7M**) feasible 40/40 never−1.
Looked like cap20 = 3.5× WORSE.  **But it's a MEASUREMENT ARTIFACT**, not a cap effect:
- Catastrophe concentrated in prob_27 (38.7M→295.7M, base z1 9864→50233), prob_38
  (61M→263M, orig fell back checkpoint:phase1), prob_25 (465K→2.69M).
- ROOT: the BASE solver (best-of v2+orig) drew a BAD solution in the cap20 run on those
  3 high-variance instances.  PROOF cap is innocent:
  (1) grep: unified_greedy / solver_orig / gassign do NOT import crane_cpsat/postproc/
      OGC_PP_ACTIVE_CAP — the base solvers are cap-INDEPENDENT.
  (2) postproc is provably NEVER-WORSE (only accepts strictly-improving feasible trials,
      else returns base).  cap (postproc-only) CANNOT make final < base.
  (3) cap20 prob_38 log: base 608M (orig phase1 fallback) → postproc CORRECTLY improved
      to 263M.  The 608M base is the problem, and the base ≠ cap's doing.
- ⇒ The paired full-set design does NOT control base-solver variance (±5-10× on
  prob_25/27/38) → it SWAMPS the postproc-lever signal.  Exactly the run-to-run pitfall
  the handoff warned about.  **A postproc-lever A/B MUST share the base per instance.**
- Confirm: `_varprobe.py` (postproc OFF, 3 reps, {25,27,38,30}) — expect base obj to
  swing 5-10× run-to-run.

## ✅ VARIANCE-CONTROLLED A/B (shared base, official obj, budget=60s)  [_levctl_res_*.json]
| inst | w1 | base | prod | cap20 | cap30 | cap20−prod | cap30−prod |
|---|---|---|---|---|---|---|---|
| prob_25 | 667 | 525,079 | 460,380 | 497,732 | 497,065 | +37,352 (hurt) | +36,685 |
| prob_30 | 13333 | 5,610,065 | 5,596,732 | 5,503,401 | 5,490,068 | −93,331 | −106,664 |
| prob_27 | 13333 | 37,436,477 | 36,463,168 | 35,756,519 | 35,583,190 | −706,649 | −879,978 |
| prob_38 | 13333 | 64,576,269 | 62,936,310 | 60,629,701 | 60,696,366 | −2,306,609 | −2,239,944 |
| **sum** | | | 102,387,353 | | | **−3,069,237** | **−3,189,901** |
- ALL arms improved from base → never-worse CONFIRMED → full-set 644M = base variance,
  cap INNOCENT (final proof: global_eval==official, postproc accepts only official gains).
- **cap NET WIN at production budget (60s)**: −3.07M (cap20) on these 4.  Wins the 3 big
  w1=13333 set2 instances; loses only prob_25 (w1=667, small) +37K.
- Note the FLIP vs 300s screen (prob_30 cap was +139K WORSE @300s, now −93K BETTER @60s):
  at SHORT production budgets prod is also round-starved → cap's speed wins broadly.
  cap30 ≈ cap20 (slightly better net here).

## Base STABLE under clean runs  [_varprobe, postproc OFF, 3 reps]
prob_25 1.00x, prob_27 1.01x, prob_38 1.01x, prob_30 1.00x.  ⇒ the full-set 644M
catastrophe was NOT clean-run base variance — it was CROSS-ARM CONTENTION (two arms
run simultaneously; v2/orig spawn CP-SAT workers that escape the 4-core affinity →
oversubscription → base solvers time out → bad fallback bases).  cap fully exonerated.
Lesson: paired-simultaneous full-set A/B corrupts the BASE for postproc levers; use the
shared-base controlled sweep (base corruption common-mode → cancels in deltas).

## ✅✅ DEFINITIVE set2 controlled sweep (shared base, official obj, budget=60s)  [_levctl_sweep_cap_60.txt]
prod=176,829,296  **cap20=175,522,088 (Δ −1,307,208 = −0.74% NET WIN)**  cap30=176,292,957 (Δ −536,339)
- cap20 WINS 6 (prob_23/27/28/30/37/38), HURTS 11 (small amounts), TIES 3.
- **Net win is CONCENTRATED in 2 huge instances**: prob_38 −1,266,635, prob_27 −546,653
  (= −1.81M).  The other 18 net +0.5M (cap mildly HURTS).  ⇒ fragile, trade-off lever.
- cap20 > cap30 (cap30 hurts small instances more).  never−1 safe (never-worse vs base).
- VERDICT: cap20 = real but MODEST + FRAGILE net obj win, carried by 2 instances, at the
  cost of mildly hurting 11.  By "total obj" rule it wins; by per-instance rank it's a wash.
  Budget-dependent: screen @300s had prob_38 −4.5M (win GROWS) but prob_30 +139K (small
  loss GROWS) → at competition-long TL the big wins likely dominate MORE.

## Other levers controlled sweep (8 instances, budget=60s)  [_levctl_sweep_other_60.txt]
prod=132,093,960. Δ vs prod: blocker −212K, xsmart −1,453,957, blprobe3 −437K,
tighten −482K, **cap30bl(cap30+blprobe) −3,488,369**.  NOT neutral as smoke suggested!
- All net-HELP on this subset; carried by big instances prob_27/38.  xsmart & cap30bl
  look strong; blocker/blprobe/tighten near aggregate noise (~±850K over 8 instances).
- ⚠ SINGLE-RUN → CP-SAT postproc noise contaminates (handoff: "<300K = noise", "단일
  캡처 랭킹 신뢰 금지").  Need REPEATS to separate signal from luck.

## NOISE-CONTROLLED repeat test (3 reps/arm median, shared base, budget=60s) [_levrep_res_*]
SUM Δmedian over {27,38,30,33,39}: cap20 −2,026,610, xsmart −519,980, cap30bl −2,939,929.
cap20 REAL win 4/5 (loss prob_33 +80K only); cap30bl bigger.  ⇒ levers are NOT noise —
REPRODUCIBLE real net wins.  (Initial pessimism reversed.)

## ✅✅✅ FINAL full set2 sweep (shared base, budget=60s)  [_levctl_sweep_final_60.txt]
prod=177,281,729  cap20=175,707,062 (Δ −1,574,667 = −0.89%)  **cap30bl=174,743,224
(Δ −2,538,505 = −1.43%)**.  cap30bl CLEARLY best (blprobe synergy: bigger wins on
prob_27/32, FIXES cap20's losses on prob_31/37).  losses small (prob_35 +160K worst).

## ★ ADOPTED: cap30bl = OGC_PP_ACTIVE_CAP=30 + OGC_PP_BLPROBE=3
- myalgorithm.py setdefault added (v7).  Rebuilt zip: `submissions/v-cap30bl-2026-06-25.zip`
  (0.45MB, 43 entries, standalone prob_21/38 feasible).
- never−1 SAFE by construction: postproc never-worse under official obj (global_eval==
  official) → cap/blprobe can only improve or no-op the base → ZERO added −1 risk.
- Clean ALL40 @TL=120 verification RUNNING (single-config, avoids the paired-contention
  artifact).  [_verify_all40.txt]
- Budget note: production leftover (~20-40s @TL=120) is SHORTER than the 60s test →
  round-starvation worse → cap helps ≥ measured.  At competition-long TL the big-instance
  wins GROW (screen: prob_38 −1.27M@60s → −4.5M@300s).

## prob_38 @ TL=600 step timeline (cap30bl)  [_run38_detailed.json, docs/prob38-step-timeline-2026-06-25.html]
total wall 560s, FINAL obj 57,096,456 (z1 4146). 스테이지:
| stage | dur | elapsed | obj | note |
|---|---|---|---|---|
| v2 greedy | 84s | 84s | 61,389,682 | best-of base |
| orig solver | 345s | 429s | 84,967,913 | **WORSE than v2 → best-of DISCARDS (345s 낭비)** |
| postproc(cap30bl) | 131s | 560s | 57,096,456 | v2 base서 −4,293,226 (−7%) |
- postproc = 1 round 만 fit(9패스 x/y/o × 3 tardy 베이, 8/9 수락): bay2 x−907K/y−27K/o−387K,
  bay1 x−893K/y−253K/o−453K, bay0 x−787K/y−587K/o(reject). x-패스가 최대 reducer.
- ★ACTIONABLE: orig가 prob_38서 v2에 짐(345s=57% 낭비), postproc(진짜 reducer)는 123s로 STARVED.
  예산 재배분(orig↓ postproc↑)이 prob_38 큰 upside(300s postproc→−4.5M+ screen) — 단 orig는
  다른 인스턴스서 이김(set1) → 인스턴스 의존, 단일 config로 적응 필요. (미검증 후속 레버)

## prob_38 @ TL=600: orig-included vs NO-ORIG (give postproc the time)  [_run38{,_noorig}_detailed.json]
| | orig 포함 (현 프로덕션) | orig 제거 (v2+postproc) |
|---|---|---|
| v2 | 84s → 61.39M | 84s → 60.20M (v2 변동 ~1.2M) |
| orig | 345s → 84.97M (폐기) | SKIP |
| postproc | 123s → 57.10M (1라운드, Δ−4.29M) | **468s → 53.15M (2라운드+moveall, Δ−7.06M)** |
| **FINAL** | **57,096,456** | **53,145,787 (−3.95M, −6.9%)** |
- postproc Δ가 −4.29M(123s)→−7.06M(468s) = **+2.77M attributable to budget**(나머지 ~1.2M=v2 변동노이즈).
- 468s postproc: round1(9패스 −5.04M)+moveall(−0.51M, **budget있을때만 fire**)+round2(−1.5M, 체감).
- ★시사점: prob_38(거대 set2, v2가 orig 격파)에선 orig가 시간만 낭비 → postproc 재할당이 큰 upside.
  BUT orig는 **set1(z1=0)서 강함** → 전역 제거는 set1 파국. 답지튜닝 금지 → **solve-time 적응 재할당**
  (v2가 orig 이미 압도하는 인스턴스서 postproc에 시간↑)이 진짜 레버 — **full-set 검증 필요(미검증)**.

## Final lever verdicts (all gated; prod = cap30bl ON, rest OFF)
| lever | verdict |
|---|---|
| P1① active-cap (CAP=30) | ADOPTED (part of cap30bl) |
| P2② blprobe (=3) | ADOPTED (part of cap30bl) |
| P1③ memo | safe/output-invariant but speed-only, marginal at prod budget — OFF |
| P1② K, P3 blocker, P2① xsmart, P4b tighten | net-neutral-to-weak alone — OFF |
| P1④ bitmask | FALSIFIED unsafe — never |
| P4a z2-proxy | deferred (reasoned) — not built |

## Open: budget-dependence of cap net win (run budget=200 cap sweep on set2 to confirm
   the win grows at competition-like TL).  If yes → adopt cap (build ADAPTIVE large-bay-only
   variant to drop the 11 small-instance losses).  If no → keep gated OFF.
