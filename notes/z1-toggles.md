# Z1(Tardiness)→0 레버 토글 맵 (2026-06-06, +2026-06-07 default 통합)

## 🎉🎉 2026-06-07: **20/20 Z1<20 달성** (시작 3/20)
**시간특성(robustness)**: 300s=20/20(×2재현). 120s=18/20 — prob_14/20(최대 250/300블록)만 시간부족. reserve↑(35%) 는 **악화**(prob_20 507→552): 서치가 base 만들 시간이 핵심, 큰 인스턴스는 full budget 필요. eval(수분~30분/4코어)은 큰 인스턴스에 더 주므로 OK. 18/20 은 120s 내 crack(빠름). prob_20 300s=9~14(여유), 더 주면↓.

env 없이 자동. 0=14개(prob_1/2/3/4/5/6/7/8/9/10/16/17/18/19), prob_11=1,15=2,14=4,13=10,12=11,**prob_20=14**. 단위 11/11 통과, 전부 feasible·gated(objective-safe).
**최종 레버 파이프라인**(postprocess, 전부 default ON): cum_level(α90;85;80×order best-of) → cpsat_timing → **bbox_pack**(per-bay 2D CP-SAT, footprint disjoint when time-overlap) → **cross-bay relocate(use_bbox=ON, drop-source, 40moves)** → bbox_pack2 → exit_pull/reschedule/shift/tardy_redecode/single_move. + 진입부 cum_level/cpsat 예약(reserve22%).
**핵심 돌파**: ① cum_level(수요평탄화) 3→14, ② cross-bay relocate(과부하베이→빈베이) 14→17, ③ **bbox_pack**(공간+시간 동시 2D CP-SAT, greedy 단편화 해결) 17→19, ④ **bbox-aware cross-bay**(이동을 bbox-pack 으로 평가→roomy 베이 on-time 착지) 19→**20**. 진단주도(tardiness 분포+per-bay demand 측정→구조맞춤 레버)가 blind 튜닝 실패를 이김.



## ★★ 통합된 submission 기본설정 (2026-06-07) — env 없이 자동 적용
- `OGC_CUMLEVEL=ON`, `OGC_CPSAT_TIMING=ON`, `OGC_CUMLEVEL_ORDERS=3`, `OGC_CUMLEVEL_ALPHAS=90;85;80`, `OGC_LEVER_RESERVE_PCT=22`.
- **단일 일반설정 5분/인스턴스 결과: 14/20 Z1<20** (prob_2/3/5/7/8/10=0, 11=3,16=3,4=4,9=4,1=6,12=15,17=18,6=19). 남은 6: 19=24,13=25,14=27,15=41,18=68,20=231.
- 모든 레버 gated(objective-safe), kill-switch=env 0. 단위테스트 7/7 통과.
- 인스턴스별 분기 없음 — alpha/order 는 **런타임 best-of**(게이트가 인스턴스마다 최적 선택) → 일반화. 모든 20 인스턴스 global cumulative LB=0 (도달 가능). prob_20 은 배정-한계(현 배정 LB=62, global=0). `_temporal_reassign_redecode_verified`(OGC_TEMPORAL_REASSIGN) 시도했으나 area-balanced 배정이 2D 디코드는 더 나빠 미채택(OFF).
- 잔여 격차 = **2D packing 단편화**(greedy 디코드). 속도개선=더 많은 best-of 시도 → 더 낮은 Z1.

### ★★ cross-bay relocate **default ON** (2026-06-07) — 14→16/20
- 최종설정: cross-bay 를 cpsat_timing 뒤(=cheaper steps 앞)에서 실행하되 **15s reserve**(min(15, 0.20·remaining))를 cheaper steps 에 남김. early-full 은 prob_6 starve(19→20), last 는 prob_19 starve(24→24); **early+reserve 가 둘 다 해결**.
- **측정(early+reserve)**: prob_17 26→**11**, prob_19 24→**6** (둘 다 <20 돌파), prob_6 19→14, prob_14 17→16, prob_12 15→12 (회귀0). prob_13 31→25, prob_18 68→50(개선but>20), prob_20 231(불변, systemic overload).
- **default ON** (`_env_on("OGC_CROSSBAY_RELOCATE", True)`). gated+leftover budget → no-op 최악(회귀불가). 주의: wall-clock 의존(이동수가 시간따라 변동)이라 eval 서버 속도에 결과 약간 의존하나 게이트로 안전.
- 남은 4: prob_13(25)·15(30)·18(50)·20(231). prob_20 은 cross-bay 안먹힘(소수블록 아닌 systemic).
- **cheap-eval(2026-06-07)**: 각 재디코드 bay 는 crane-safe 보장+bay 독립 → trial 평가를 check_feasibility(0.8s) 대신 `_obj_of_results[0]`(closed-form, ~0.01s)로. **주의: `_objective` 는 튜플 반환 → `[0]` 필수**(빼먹으면 default 가 greedy baseline 으로 붕괴, prob_14 17→5222 측정함). 게이트가 최종 official check 1회. `OGC_XBAY_MOVES`(default 20) 튜닝가능.
- **40 moves 측정**: prob_13 31→25, prob_17 17→11 (margin↑) 이나 **prob_15/18 불변(30/50)** → greedy 1블록이동이 **local minimum**(과부하 bay→target 으로 tardiness 셔플만). 탈출 = **batch move**(과부하 bay 의 여러 블록을 한번에 비우고 best-prefix 유지) 시도 → **실패**(`OGC_XBAY_BATCH` default OFF): prob_13/15 불변, prob_18 50→102(악화). 원인=target bay 가 이동블록 받으면 재디코드 단편화 → tardiness 셔플만. **default 16/20 무영향**(batch OFF). 코드는 OFF 로 남김.

### ★★★★ standing (2026-06-07): **19/20 Z1<20** — bbox-pack 돌파구
- `OGC_BBOX_PACK` (**default ON**, `_bbox_pack_bay`+`_bbox_pack_redecode_verified`): per-bay 2D CP-SAT — 블록 (x,y)ref+entry, **시간겹침⟹footprint disjoint**(crane-safe+collision-free), min tardiness. bbox-conservative→official-safe, min-area orient. greedy 단편화를 **공간+시간 동시최적**으로 해결(due slack 으로 시간축 분산). cpsat_timing 뒤·cross-bay 앞.
- **측정(integrated full)**: prob_15 23→**0**, prob_18 59→**3**, prob_20 231→**68**, 다수 margin↑. 빠름(prob_15 3.7s). **19/20 <20**: 0=prob_1/2/3/4/5/7/8/10/12/15/16, 1=9/11/19, 3=17/18, 7=14, 8=6, 10=13. **남은 1=prob_20(68)**.
- prob_20=배정-한계(현배정 bbox floor~68, global LB 0이나 area-relaxation). temporal_reassign+bbox=154(더 나쁨, area-balance≠good). → global combined(배정+2D packing) 솔버 필요.

### (이전) **17/20 Z1<20** (drop-source cross-bay)
- drop-source: source bay 블록제거시 재디코드 불필요(feasibility 보존)→target 만 재디코드→2× moves. `OGC_XBAY_MOVES`=40, `OGC_XBAY_CANDS`=2(4 는 예산먹어 악화). **prob_13 25→17 돌파**. <20=17개. 남은 3: prob_15(23)·18(59)·20(231).
- prob_15 막힘=**target-bay fragmentation**(이동블록이 받는 베이서 tardy). more-cands/batch/retime 다 실패. cross-bay greedy 한계.
- 진짜 20/20 = combined 배정+2D packing 솔버(대규모). 17/20 은 검증·통합·제출가능(점수 rank 기반 매우 경쟁력).

### (이전) 최종 standing (2026-06-07): **16/20 Z1<20** (검증·통합 완료)
- env 없이 자동: cum_level(α 90;85;80×order3 best-of) + cpsat_timing + cross-bay relocate(20moves, cheap-eval) + reserve. 단위테스트 통과, 회귀0.
- <20(16): prob_1/2/3/5/7/8/10=0, 16=2,11=3,4=4,9=4,19=6,12=7,17=11,6=15,14=17.
- >20(4): **prob_15=30, prob_13=31, prob_18=50, prob_20=231**. 13/15/18=overload bay(cross-bay 부분개선but local-min), prob_20=systemic(빈베이無).
- 시작 3/20 → 16/20. 남은 4 = greedy cross-bay 한계+systemic. 진짜 <20 전부 = batch packing/combined solver(대규모).

### ★ 2026-06-07 돌파 — cross-bay relocate (OGC_CROSSBAY_RELOCATE)
- 진단: 일부 above-20 는 **한 작은 베이 과부하 + 다른 큰 베이 텅빔** (prob_17: bay3 84%·tardy 8블록, bay1 36%·64% 빈). search 가 greedy 평가라 이 이동을 놓침.
- 레버: worst-tardy 블록을 **덜 붐비는 feasible 베이로 이동 + 양 베이 flattened 재디코드**, full objective 게이트(w1지배라 Z1↓이 Z3↑ 압도). 수술적(건드린 베이만 재디코드 → 나머지 좋은 패킹 보존, temporal_reassign 의 wholesale 와 다름).
- **측정: prob_17 26→10 (<20 돌파!)**. `_tardy_crossbay_relocate_verified`+`_flatten_decode_one_bay`. cum_level cap 70→50%(여유). prob_19/18/13 테스트 중. 회귀확인 후 default 검토.

### 2026-06-07 야간 실험 (모두 default OFF, 검증완료)
- **exhaustive-lever(OGC_CUMLEVEL_EXHAUSTIVE)**: prob_17 26→**120**(대패, lever 안에서도 exhaustive 너무 느림). OFF.
- **exhaustive positions(OGC_FAST_POSITIONS=0)**: prob_14 → **955**(대패). 느린 디코드=적은 iteration=나쁜 Z1. → FAST positions 가 옳음, 속도=레버 확정.
- **more-attempts(4α×4order)**: prob_14 27→25 (한계효용). 닫힌 cluster 는 **packing floor**(~24~26)에 막힘, 시도 수로 안 깨짐.
- **OGC_CUMLEVEL_PARALLEL(신규, parallel_decode.run_parallel_cumlevel)**: bay별 병렬 best-of. **검증결과 폐기**(default OFF) — prob_19 24→24(무익), prob_14 solo 538(나쁨, 워커가 예산 소진 후 미개선 incumbent 반환). 동작은 정상(feasible·무행)이나 이득 없어 OFF 유지. 코드는 남겨둠(OFF, 무해).
- **OGC_TEMPORAL_REASSIGN(신규, _temporal_reassign_redecode_verified)**: CP-SAT 배정+area-cumulative 재배정. **OFF** — prob_20 921→356(작동)이나 area-balanced 배정이 2D 디코드는 cum_level(231)보다 나쁨. 배정-한계 인스턴스(prob_20 LB62→global0)지만 area-relaxation 이 2D packability 의 나쁜 proxy.
- **결론(야간)**: 남은 6개(13/15/17/18/19/20) 는 **2D greedy packing floor** 가 벽. 더 낮추려면 근본적으로 더 나은 2D 비정형 packing(skyline/best-fit/discrete-position CP-SAT) 필요 — 대회 핵심난제, 리스크 큰 재작성. variance 로 prob_14/17/19 는 17~27 사이 진동(가끔 <20). 단일 eval 런에서 robust <20 하려면 packing floor 자체를 낮춰야 함.



## ★ CP-SAT 최적 타이밍 (2026-06-07 추가) — 신규 레버

| 플래그 | 기본 | 효과 | 비고 |
|---|---|---|---|
| `OGC_CPSAT_TIMING` | **OFF** | 고정 레이아웃에서 **per-bay 최적 crane-feasible ENTRY/EXIT** (CP-SAT). bay/x/y/orient 고정 → Z2/Z3 불변, Z1만↓ | `_cpsat_bay_timing_verified`, postprocess `consider` 게이트 |

**측정(isolation, base=greedy layout)**: prob_14 Z1 5222→**883(−83%)**, prob_20 1864→**1468(−21%)**. feasible·objective-safe(게이트). exit=entry+P WLOG, crane precedence=time-independent 5불리언 precompute → 순수 interval 스케줄링 CP-SAT 최적해. 기존 `_multi_order_reschedule_verified`(≤5 ordering 휴리스틱)의 **최적 대체**.

**핵심 발견**: 타이밍은 **레이아웃 bounded** — greedy 레이아웃 최적타이밍 floor=883 ≫ 풀서치 레이아웃 309. 따라서 Z1<20 경로 = **좋은 레이아웃(anti-stacking) + 최적 타이밍**. intrinsicLB=0(모든 인스턴스) 이므로 원리상 달성 가능. ([[ogc2026-z1-feasibility-floor]])

---

## ★ 디코드 가속 (2026-06-06 추가, 측정 검증) — default 변경

| 플래그 | 기본 | 효과 | 비고 |
|---|---|---|---|
| `OGC_BBOX_CACHE` | **ON** | `_aabb` 메모 → **1.27× (byte-identical, 공짜)** | kill-switch=0 |
| `OGC_FAST_POSITIONS` | **ON** | O(P²)→컬럼지지 위치 → **3.55× 디코드** | kill-switch=0 |
| `OGC_FAST_POS_TOP` | **4** | 컬럼당 바닥+상위 N레벨만 (0=전부). 4=속도/Z1 sweet spot | |

**효과(측정)**: 대형/잘리는 인스턴스 大승 — prob_20 @60s **52258→1864(−96%)**, prob_14 −65%, 분산 안정화. 소형(1/5/8) 회귀 0. **권장 submission 기본값 = 그대로(둘 다 ON).** kill-switch로 OFF 시 기존 exhaustive 디코드 복원.

**폐기(측정 후 제거)**: `OGC_FAST_POS_ADAPT`(worst-of-both)·`OGC_FAST_FALLBACK`(wall초과)·`OGC_DECODE_EARLY_EXIT`(Z1 trade, OFF노브)·`OGC_FAST_CRANE`(더 느림).

**한계**: 하드 인스턴스는 ~300~420 **탐색 basin**에 plateau (시간·튜닝 무관). 5분 내 두자릿수 Z1 = **full CP-SAT/LBBD 결합모델**(insight ⑤④) 필요.

---

> 문헌 인사이트 ①–⑧(`research/z1-tardiness/`)을 **켜고 끄는** env 플래그 레퍼런스.
> 핵심 안전장치: **모든 후보는 최종 official-checker 게이트**(`_postprocess_verified_solution`의 `consider`,
> 그리고 `algorithm()` 말미의 candidate 게이트 `better_obj`/`same_obj_lower_z1`)를 통과해야 채택된다 →
> **어떤 플래그를 켜도 verified incumbent/baseline floor보다 나쁜 해는 반환되지 않는다(−1·objective 악화 불가).**
> 모든 신규 Z1 플래그 default **OFF** → 미설정 시 솔버 동작은 기존과 bit-identical.

## 한눈에

| # | 인사이트 | 플래그 | 기본 | 상태 | 효과 |
|---|---|---|---|---|---|
| ① | sequence↔timing 분리, 정확 재타이밍 | **`OGC_Z1_MULTI_RESCHED`** | OFF | **신규** | 레이아웃 고정·다중 crane-safe 순서로 ENTRY/EXIT 재계산, bay별 최소 tardiness 채택. **x/y/orient/bay 불변 → Z2/Z3 불변, Z1만↓** |
| ② | per-bay tardiness 하한 focus | **`OGC_Z1_LB`** | OFF | **신규** | `Σmax(0,r+p−due)` 하한에 이미 도달한 베이를 skip → 예산을 회수가능 베이에 집중 |
| ①②| 마스터 스위치 | **`OGC_Z1_PUSH`** | OFF | **신규** | 위 ①+② 동시 ON (가장 안전한 Z1 푸시) |
| ③ | 마감-인지 배치 (slack+crane 우선) | `OGC_CRANE_ORDER` / `OGC_ATCR_SEED` | ON / OFF | 기존 | `_orderings`가 slack·crane-complexity로 정렬(통로 보존). ATCR 켜면 ATC 순서 추가 |
| ④ | LBBD / no-good cut | `OGC_M4_CUT`(+ALNS `op_cut_destroy`) | OFF / 항상 | 기존 | force-place 인증을 읽어 over-subscribed 베이의 블록을 eject + 그 조합 cut |
| ⑤ | CP-SAT 배정 시드 | `OGC_CPSAT_FIRST` | OFF | 기존 | CP-SAT(OR-Tools)로 배정 시드 → gated candidate (ortools 필요) |
| ⑥ | tardiness-타겟 ALNS destroy | (ALNS `op_destroy_repair`, 항상) | 항상 | 기존 | destroy의 50%가 worst-tardy 우선 제거 + regret 재삽입 |
| ⑦ | 탐색 SA accept-worse | `OGC_SA_TEMP` | 0.10(regime) | 기존 | 내부 local search의 일시적 악화 허용 온도 (반환은 안전게이트 유지) |
| ⑧ | ATC dispatch 순서 | `OGC_ATCR_SEED`(+`OGC_ATCR_K`) | OFF | 기존 | EDD 대신 ATC(urgency×slack) 순서 후보 추가 |

> ⑥⑦은 search가 돌 때 항상 활성(개별 플래그 아님). ⑦ 온도는 `OGC_SA_TEMP`로 조절.
> ⑧·`OGC_CRANE_TIEBREAK`은 과거 **소형 인스턴스 회귀**로 default OFF (메모리 `ogc2026-z1-lever-is-packing`). 켤 땐 소형 회귀 확인 필수.

## 관련 보조 노브

| 플래그 | 기본 | 역할 |
|---|---|---|
| `OGC_GATE_POSTPROCESS` | ON | postprocess 게이트(exit_pull·reschedule·shift·redecode·**multi_reschedule**) 활성 |
| `OGC_Z1_BAY_DECODE` | ON | 같은 배정을 베이별로 깨끗이 재디코드하는 gated candidate (`run_parallel_bay_decode`) |
| `OGC_PARALLEL_MS` | auto(T≥20 & n≥30) | 4코어 병렬 multistart (1=강제ON, 0=강제OFF) |
| `OGC_CRANE_MOVE_CAP` | 80 | `_tardy_redecode_moves`의 후보 cap |
| `OGC_CAND_CAP` / `OGC_CAND_CAP_MIN` | 0 | 디코드 후보 가지치기(대형 가속, 소형 보호) |
| `OGC_CRANE_TIEBREAK` | OFF | 동점 move를 crane 방향으로 tie-break (소형 회귀 주의) |

## 사용 예시 (PowerShell)

```powershell
# 가장 안전한 Z1 푸시 (신규 ①+②) — 단일 인스턴스
$env:OGC_Z1_PUSH = "1"
conda run -n ogc2025 python tools/run_solver_once.py instances/train/prob_14.json --solver our --timelimit 180
Remove-Item Env:OGC_Z1_PUSH   # 끄기

# 개별 레버만
$env:OGC_Z1_MULTI_RESCHED = "1"          # ① 만
$env:OGC_Z1_LB = "1"                      # ② focus
$env:OGC_CPSAT_FIRST = "1"               # ⑤ CP-SAT 시드
$env:OGC_ATCR_SEED = "1"; $env:OGC_ATCR_K = "2.0"   # ⑧ ATC (소형 회귀 주의)
$env:OGC_SA_TEMP = "0.15"                # ⑦ SA 온도 ↑
```

```bash
# bash
OGC_Z1_PUSH=1 conda run -n ogc2025 python tools/run_solver_once.py instances/train/prob_14.json --solver our --timelimit 180
```

## 검증

- A/B 하니스: `notes/_z1_ab.py` → `results/z1_push_ab.json` (base vs push, feasible·objective-safe·Z1·wall).
- 단위: `conda run -n ogc2025 python -m pytest tests/test_safe_foundation_contract.py tests/test_parallel_pickle.py tests/test_smoke.py -q`
- objective-safety 불변식: 어떤 조합도 `push.objective ≤ base.objective` 이고 `feasible=True` (게이트 보증).

## 미구현(향후, 본격 작업 필요)

- ⑤ **per-bay 정확 CP-SAT 재패킹**(no_overlap_2d + j≥k precedence를 utils 기하와 정합): 현재는 CP-SAT **배정** 시드만 존재. 완전 재패킹 모델은 utils crane 기하 복제가 필요해 별도 큰 작업·시간상한 위험 → 게이트 보호 하에 추후.
- ④ **완전 LBBD**(CP-SAT master + cut): 현재는 휴리스틱 no-good destroy(M4)로 근사. master를 CP-SAT로 올리는 건 별도 작업.

## ★ 안티스태킹/수요평탄화 (2026-06-07) — 신규 레버 + 한계 측정

| 플래그 | 기본 | 효과 | 비고 |
|---|---|---|---|
| `OGC_CUMLEVEL` | **OFF** | per-bay cumulative CP-SAT 로 tardiness-최소 ENTRY 타깃 → effective release=max(release,target) 로 재디코드(수요 평탄화) | `_cumulative_leveled_redecode_verified`, gate |
| `OGC_CUMLEVEL_ALPHA` | **90** | cumulative 용량=alpha%·floor (packing 여유). prob_14 LB: a=1.0→0, .9→0, .8→4, .7→19 | |
| `OGC_LEVER_RESERVE_PCT` | **22** | 레버 ON 시 서치 deadline 을 이만큼(%·T) 당겨 **후처리 레버에 예산 확보**. 큰 인스턴스에서 서치가 예산 다 써서 레버 스킵되던 것 방지 | algorithm() 예산설정 |

**통합 5분 풀스윕(v1, reorder 전)**: **10/20 Z1<20**. 큰 인스턴스(prob_15/17/20)는 서치가 예산 독식 → 레버 스킵(951/1011 그대로).
**reorder 수정(2026-06-07)**: cum_level 이 후처리 체인 **맨 뒤**라서 exit_pull/reschedule/shift/tardy_redecode 가 큰 인스턴스서 ~90s 헛소비(Z1 0개선) 후 cum_level 에 **9.8s만** 남겨 garbage(2953) 거부됨. → **cum_level 을 후처리 맨 앞으로** 이동(window 70% cap, 나머지 30% 는 cpsat_timing+값싼 step). 결과 **prob_15 951→48** 확인. `OGC_LEVER_DEBUG=1` 로 예산흐름 stderr 추적 가능.
**남은 cluster(~20~60)**: cum_level greedy 재디코드의 **2D packing 단편화** 가 floor. multi-attempt/multi-alpha/better-packing 필요. prob_20(~258)은 최대난제.

**측정(2026-06-07)**: per-bay **cumulative area LB(Z1)=0** (α≥0.9, 모든 베이 OPTIMAL) → 수요는 slack 쓰면 floor 안 넘침, 관측 Z1 전부 greedy enter-ASAP 피크+2D 패킹 단편화. 그러나 **realize 가 벽**: cum_level 재디코드 prob_14(base90)=1419→852→(cpsat)508, prob_20 1009→1885(gate 거부). **greedy 재디코드(508)가 ALNS 240s 서치(309)보다 나쁨** → flatten 은 naive 대비 도움이나 ALNS 못 이김.

**결론**: Z1<20 의 진짜 벽 = **2D 비정형 packing-over-time 조정**(coordination). 타이밍(CP-SAT 225)·수요평탄화(508) 둘 다 packing 한계에 막힘. <20 = full combined 2D packing 솔버 필요(경쟁 핵심 난제). 두 레버 모두 gated-safe(최종해 악화 불가), default OFF 유지.
