# OGC 2026 — 마일스톤 완료 상태 (2026-05-30)

> `notes/dev-plan.md`(SSOT)의 마일스톤 M0–M6 + perf 트랙 통합 결과 기록.
> 모든 변경은 `src/myalgorithm.py`(엔트리) + 헬퍼 모듈. `utils.py`·`baseline/` 미수정.

## 완료 요약

| 항목 | 상태 | 핵심 |
|---|---|---|
| **M0** 생성기·벤치 | ✅ | `gen_instance.py`, `bench.py`, 17개 gen 인스턴스 |
| **M1** 모듈 경계 | ✅ | 단일 파일 + 헬퍼(`baseline_greedy`,`geom_kernel`,`regime`,`parallel_decode`,`instrument`) |
| **M2** 기하 커널 | ✅ | `geom_kernel` suffix-OR 크레인 마스크 + raster — `baseline_greedy._find_earliest_slot`에 **prefilter로 연결**(가속), 정확성은 항상 `check_feasibility`가 권위. soundness 테스트(`test_geom_kernel`) + 시스템 feasibility 테스트(`test_feasibility`) |
| **M3** ALNS | ✅ | shift / swap / destroy-repair + 적응 룰렛 + SA 수용 + stagnation stop |
| **M4** no-good-cut seam | ✅ | `_decode_bay`→`forced_ids` 인증서, `_Decoder` 3-tuple 캐시 + `decode()` 2-tuple **방화벽** + `decode_full()`, `op_cut_destroy` + `cut_store` tabu. **over-subscription(force-place OR 지연 Z1>0)이 있을 때만 op_cut_destroy 등록** → Z1=0 인스턴스(gen 전부)는 연산자 3개 그대로 = **bit-identical M3**(example 1022.70). 강제 over-subscription 인스턴스(12블록·2베이·전부 [0,12])에서 **op_cut_destroy 발화 117회 확인**(feasible 유지, 대칭이라 개선 0=정상). floor+gate로 feasibility 보장 |
| **M5** 4코어 병렬 | ✅ | `parallel_decode.run_parallel_multistart` — 독립 시드 multi-start(spawn, ≤4 워커, pickle-safe). **never-raises → None 폴백**(서버 mp 차단/실패해도 −1 불가). 워커가 results까지 반환 → 부모 무가드 재디코드 제거. 게이트 `timelimit≥20·n≥30·n_bays≥2` |
| **M6** 레짐 라우팅 | ✅ | `regime.py`(stdlib-only) — w1/w2/w3 × loose/tight × n → decomposition/tossup/escape. **search 노브만 연결**(seed 순서·op 가중치·SA 온도·cpsat) — work_frac/hard_stop_frac은 하드코드 유지(레짐이 −1 타임가드를 못 건드림). 기본값=현재 동작(UNKNOWN/TOSSUP no-op) |
| **perf** 타임가드 | ✅ | `_DECODE_SAFETY=1.8` — 디코드 비용 추정 인플레이션으로 admit된 원자 디코드가 항상 deadline 전 종료(wall-clock 87%→~78%) |
| **perf** check_cost 재보정 | ✅ | `0.0006·n²`(n80에서 4.04s 과대) → `0.0001·n²+0.3`(실측 0.015s). baseline budget 0.80×T 상한 제거 → baseline-bound 인스턴스에서 표준 baseline과 매칭 |

## 검증 (timelimit 60s, env ogc2025/py3.11)

- **gen 스위트 17개**: feasible **17/17**, 타임아웃 **0**, 회귀 **0**, 개선 4건(s1 +50.5%, s2 +97.1%, s4 +62.5%, s6 +73.4%), 평균 16.67%. 최대 wall-clock ~46s(76%).
- **example_B2_b10**: 1022.70 — M4/M5/M6 통합 후에도 **bit-identical**(no-op 경로 확인).
- **dense stress 4개**(density 0.63–0.75): feasible **4/4**. s202(n80 w3)는 60s에서 −2.5%였으나 **120s에서 정확히 동점**(`delta=0.0`) → 빡빡한-60s artifact, 현실적 timelimit에선 무회귀.
- **단위테스트**: 전체 pytest **40/40 통과** (smoke·regime·geom·parallel pickle+spawn·m4_contract·feasibility 17개). M4 재타겟 후 gen 재벤치도 17/17·무회귀·16.67% 동일(bit-identical 확인).
- **M4 발화**: 강제 over-subscription 인스턴스(12블록·2베이·전부 [0,12])에서 `op_cut_destroy` 4번째 연산자 등록 + **117회 발화**, feasible 유지.

## 제출 무결성

`build_submission.py`가 `src/*.py`(myalgorithm·baseline_greedy·geom_kernel·instrument·regime·parallel_decode) 전부 zip 루트로 평탄화 → bare import 동작, utils.py 제외, ≤15MB.

## 진단 (2026-05-30): "서치가 시드를 한 번도 못 이긴다"의 원인

로그 분석으로 search_end의 `op_improves`가 **모든 트레이스에서 [0,0,0]**(개선 이동 0, 한 트레이스는 51만 iter·8,605 restart에도 0)임을 발견. cpsat에 optimality-gap 계측을 추가(`_cpsat_assignment(diag=...)`, OGC_TRACE 무장 시에만 채워지는 관측 전용, 제출 동작 불변)하고 gen+stress 전체를 T=60(cpsat 10s 캡)으로 재측정한 결과:

- **21개 중 19개: cpsat가 배정-레벨 최적을 *증명*(gap=0.0)**, 대부분 ms~7s. → 배정-레벨 ALNS가 개선할 게 **수학적으로 존재하지 않음**. 즉 0-개선은 **버그 아님, 정상**(안전한 최적성 확인기). 시드+디코드 아키텍처가 건전.
- **s12 (n120·w2·m4): FEASIBLE, gap=16.4%** (obj 2,760,250 vs bound 2,306,234). cpsat가 10s 안에 balance-IP를 못 증명한 **유일한 헤드룸**. 결과는 baseline과 정확히 동점(개선 0%) → 시드도 서치도 이 갭을 못 먹음. 동점=만점이라 −1 위험은 없고 "점수 흘림"일 뿐.
- **s202(n80·w3·dense), s204(n100·w1·dense): cpsat SKIPPED("no time")** — 느린 baseline greedy(예: s13은 Phase1만 38s)+시드 디코드가 budget을 다 먹어 cpsat가 시작도 못 함. pref/balanced 시드+verified floor로 feasible 유지.

**결론**: 무거운 M3/M4 서치는 "안전하지만 무의미"가 맞다(헤드룸이 거의 없음). 추가 점수 레버는 **서치 연산자가 아니라 옵티마이저/파이프라인 앞단**에 있다 — ① w2-대형에 cpsat 시간 추가/웜스타트, ② dense-대형에서 cpsat가 항상 돌도록 파이프라인 순서/예산 보호(cpsat는 ms로 끝나니 항상 돌리는 비용이 사실상 0). 전 인스턴스 feasible·≥baseline이라 이는 순수 upside이고 "잘 돌아감" 목표는 충족.

## 돌파구 (2026-05-30): crane-safe 디코드 — Z1 일반화 개선

목표 "example 1022→600"을 받고 먼저 **example이 증명된 전역최적(1022.70)**임을 확인: 1024배정 전수조사 + cpsat gap=0이 소수점까지 일치(`obj2=14.6713, obj3=46.0, Z1=0`). 즉 example 600은 정직한 수단으로 불가능. 사용자 승인하에 **Z1(tardiness) 레버**로 전환.

진짜 병목 발견(`tools/gen_instance.py`에 `--rel-window` 추가해 clustered-release tardiness 인스턴스 생성→측정): w1-대형 congested 인스턴스에서 우리 시드는 **Z1=0을 달성하지만 그 디코드가 stage-2(크레인 ENTRY)에서 infeasible** → gate가 기각 → baseline floor로 추락(예 s703: 시드 obj 7524인데 반환은 baseline 34744). 원인은 `baseline._find_earliest_slot`가 **새 블록만** 검증하고, 새 블록이 *먼저 놓인* 블록의 크레인 진입을 *소급적으로* 막는 경우(B가 A의 entry 시점에 present)를 놓치는 것.

**수정**: `_find_slot_crane_safe`(myalgorithm.py) — `_find_earliest_slot`와 동일 + **소급(retroactive) 양방향 크레인 검사**(새 블록이 자기 window가 걸치는 모든 기존 블록의 entry/exit를 막지 않는지) + 시간겹침 전체 쌍 충돌검사. 귀납적으로 베이 전체가 stage-2/3/4 feasible. `_decode_bay`가 이걸 사용(`OGC_CRANE_SAFE` 기본 ON, kill-switch). 소급 검사는 *시간 겹치는* 블록에만 작동 → 비congested 인스턴스에선 비용 ≈0(example 5.26s 불변).

**2차 개선 — budget-bounded decode**: 대형·고밀도 시드는 전체 크레인 탐색이 decode_deadline을 넘겨 **통째로 SKIP→baseline 추락**했다(s15 n120·w2: cpsat gap 6.6% + 시드 전부 skip). 수정: `_decode_bay(deadline=...)` — deadline 경과 시 남은 블록을 빈 윈도우로 force-place(직렬화·feasible 보장). seed 루프가 skip 대신 **budget-bounded 디코드**(deadline=decode_deadline−1.5, EDD-only, 캐시 안 함)를 시도. **회귀 위험 0**: 원래 skip되던(=baseline로 가던) 시드만 새로 feasible 후보를 만들 뿐, 승자 디코드 경로는 무변(deadline=None). `OGC_BUDGET_DECODE` 기본 ON.

**검증 결과 (T=60, 0 timeout, 전부 feasible) — crane-safe + budget-decode 누적**:
- **gen 평균 개선 16.67% → 59.94%** (3.6배). w1/w2 대부분 90~99%: s5 +98.8%, s6 +97.5%, s7 +97.8%, **s9 +98.8%**, s12 +98.1%, **s15 +98.2%**(decode-bound 해소), s2 +97.1%.
- **stress 평균 +47.17%**: **s203 +99.7%**(6,205→17), s201 +92.7%.
- **tardiness 시연** s703(clustered): **34,744 → 7,524 (−78%, Z1 11→0)**.
- pytest **40/40**, example **1022.70 bit-identical**(저밀도라 무영향), 회귀 0.
- 안전성: floor+gate 불변이라 crane-safe/budget-decode가 틀려도 −1 불가(infeasible→baseline). 0 timeout으로 `_DECODE_SAFETY=1.8` + budget-decode의 1.5s 패드가 dense에서도 충분함을 실측 확인.

**부수 개선(같은 작업)**: Z1-aware **tardy 시드**(w1-지배일 때만, 시간-혼잡 분산), cpsat **웜스타트**(balanced 시드 AddHint), **floor-verify deadline을 hard_stop으로**(늦게 끝난 baseline도 floor 승격). M4/M5는 격리/OFF(아래 플래그).

**제출 feature-flag(전부 평가서버 기본값으로 ship)**: `OGC_CRANE_SAFE`(ON), `OGC_BUDGET_DECODE`(ON), `OGC_CPSAT_FIRST`(OFF — 벤치가 dense에서 net-negative 판정), `OGC_PARALLEL_MS`(OFF — 0-개선 ALNS 4코어 낭비), `OGC_M4_CUT`(OFF — opt-in).

## 알려진 한계 / 다음 후보

- **잔여 60s-0%의 실체(300s 검증)**: budget-decode가 decode-bound 대형(s15 등)을 해소한 뒤 60s에서 0%로 남던 것은 두 종류 — ① **w3-지배(s3·s8·s10·s13·s17)는 cpsat gap=0 = 이미 최적**(300s에서도 s13=211,335=baseline, 동점이 정답), ② **dense-w1(s204)는 60s에선 decode-bound로 동점이나 300s에선 10,823→10,522로 baseline을 *이김***(decode-bound이지 saturated 아님). **시사점: 대회 현실 timelimit(수 분~30분)에선 60s 벤치(gen 59.94%)보다 점수가 더 좋다** — decode-bound 인스턴스가 시간을 받으면 개선됨. 즉 모든 인스턴스가 *개선되거나 증명된 최적*이다. 더 짧은 timelimit까지 끌어오려면 디코드 가속(raster)이 레버지만 대회 현실 한계에선 부수적.
- **빡빡한-한계 60s artifact**(s202): n80·w3·dense에서 우리 내부 baseline이 reference보다 적은 budget을 받아 floor 품질이 약간 낮음 → 60s에서 −3.7%. **대회 현실 한계(≥120s)에선 baseline이 decode_deadline 내 완료→floor 승격→동점**. base_budget 상향은 large-n floor-verify와 상충해 보류(범위 외).
- **M4 cut / M5 parallel은 OFF(opt-in)**: 둘 다 증명적 0-개선(`op_improves` 전 트레이스 0). M4는 `OGC_M4_CUT`, M5는 `OGC_PARALLEL_MS`로 켤 수 있으나 기본 OFF(미실측 −1 꼬리·4코어 낭비 제거). crane-safe가 Z1을 디코드 단계에서 직접 줄이므로 cut 연산자 의존도 자체가 낮아짐.

## 디코드 가속 조사 (2026-05-30): 빠른 디코드는 레버가 아님 — OFF

decode-bound 대형(s204 등)을 더 끌어올리려 **crane-safe 슬롯파인더 가속**을 설계·구현했다(`_find_slot_crane_safe`의 fast path, `OGC_FAST_CRANE`): 크레인/충돌 기하검사는 *위치에만 의존하고 진입시각과 무관*하므로, 후보-진입 루프 밖에서 위치당 한 번만 precompute → O(i²)→O(i) Shapely/위치 (per-decode **exact**). 3-에이전트 설계 워크플로우로 ROI/위험 순위화 후 채택.

**그러나 A/B 결과 net-negative라 기본 OFF로 ship**: fast path는 *per-decode*는 동일하지만 디코드가 빨라지면 **timing-의존 budget-decode가 tail을 덜 force-place**한다 → 더 많은 crane-safe 오버랩 패킹. 그런데 tardiness 인스턴스에선 **부분 직렬화(force-place)가 full 패킹보다 낫다**(오버랩 패킹이 exit를 미뤄 Z1↑). 실측 s703: slow(직렬화 多)=859 vs fast(패킹 多)=7,524. 의도한 decode-bound 이득(s204)도 안 생김(여전히 10,822). **결론: 이 문제에서 레버는 디코드 *속도*가 아니라 패킹↔직렬화 트레이드오프**다. fast path는 `OGC_FAST_CRANE`로 격리(기본 OFF), 검증된 budget-decode 상태(s703=859, gen 59.94%) 보존. (남은 이론적 레버: budget-decode를 wall-clock 비의존·결정론적으로 만들어 직렬화 비율을 명시 제어 — 범위 외.)

## 돌파구 (2026-05-30 오후): 대형×고밀도 부진 — feasible 시드 banking (토론+계측)

3-에이전트 전문가 토론(`notes/large-dense-debate.html`)으로 대형×고밀도 부진(s204 0% 동점, s202 −2.5%) 근본원인 규명·해결. **결정적 실험과 트레이스가 세 R1 처방과 진단 오류 2회를 모두 정리.**

**근본원인 (트레이스로 확정)**: s204(w1-지배)의 CP-SAT 배정은 파이프라인 안에서 **feasible 894로 멀쩡히 디코드**된다(deadline=None/+25/+8/+4/+2/+1s 전부 게이트 stage 5 feasible). 그러나 직후 `_local_search`가 그 시드에서 출발해, **같은 `quick_obj`(=배정+exit시각에만 의존, x,y 위치 무시)의 *다른* 레이아웃**으로 바꿔치기 → 그 사본이 크레인 stage-2 infeasible → `candidate("search")`로 등록 → 게이트가 검증·기각 → feasible 원본은 후보에 없어 baseline floor(10,822)로 추락. 즉 **서치가 feasible 시드를 오염시키고 원본은 버려졌다.**

**w1/w3 갈림**: s204(w1)는 분산 배정이 Z1=0 달성 → 894 승리 실재. s202(w3=2667)는 모든 블록 최선호가 한 베이라 **쌓기({80,0,0})가 Z3=0 최적**, 분산(balanced)은 Z3 폭발(7,531,773) → **이길 수 없고 baseline 동점이 정답**. 기존 −2.5%는 60s 타이밍 아티팩트.

**폐기된 시도 2건 (정직 기록)**: ① seeds-first 재정렬 → s202 obj 223,112·벽시계 126% 회귀. ② clean-decode 강제(비용추정 우회) → 트레이스로 디코드는 원래 멀쩡함이 드러나 무의미. 둘 다 되돌림.

**최종 수정 (`OGC_PROTECT_SEED` 기본 ON, ≈8줄)**: seed 디코드 직후 분산 시드(cpsat·balanced)의 feasible 결과를 **서치가 손대기 전에** 게이트 후보 `seed_*`로 banking. 디코드 경로·baseline·floor·gate·파이프라인 순서 전부 불변. **회귀 구조적 불가**: banking은 후보 풀에 순수 추가만 하고 게이트는 feasible 후보 중 최소 obj 선택 → 모든 인스턴스 결과 = min(기존, 새 banked feasible) ≤ 기존.

**검증 (T=60, 단독 격리=경합 0)**: s204 10,822.9→**894.8(−91.7%)**, s202→**동점**(정답), example **1022.70 불변**, 전부 feasible. (전 스위트 순차 벤치 `results/_final_regression.log` — gen/stress/tard 무회귀 확인 중.) 잔여: s204 벽시계 86%는 서치가 0.80T까지 도는 기존 동작+게이트 2검증의 60s 아티팩트(hard_stop 0.93T 밑, 51.8s 반환), 대회 현실 T에선 급락.

**살아남은 차기 레버**: ① 서치가 feasible 레이아웃을 *보존*하도록 수정(banking 의존 제거), ② 위치+시각 베이별 공동 최적화(C의 천장 — 894 아래로), ③ 솔버 팀의 dense-w1 strict 우위 가능성(B의 경고).

### 부수 발견 (2026-05-30): baseline greedy dense Phase-1 시간 취약성 (사전존재, 차기 과제)
검증 중 발견: **수정과 무관한** 기존 취약성. dense·대형(s202 n80 등)에서 `baseline_greedy`의 Phase-1 배치는 timelimit 인자를 무시하고 O(k³)로 도는데, 머신이 (장시간 부하/열로) 느려지면 ~44s→~56s+로 늘어 repair 예산을 못 받고 worse floor(s202 103,482→223,112)를 낸다. 머신이 식으면 단독 baseline=54.2s/103,482로 정상. A/B(`OGC_PROTECT_SEED` ON≡OFF=103,482.67)로 **우리 변경과 무관함 입증**. **함의**: 평가서버가 느릴 경우 dense-large w2/w3에서 baseline floor가 −1 인접 위험. 차기 과제 후보 — base_budget 재배분 또는 Phase-1 시간가드(범위 외, 본 수정과 독립).
