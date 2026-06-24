# 연구 루프 — 전역그리디 배정 + v2 패킹 + CP-SAT 타이밍

> 목표: 이 파이프라인으로 **원래 솔버를 넘는다.** 판정 = 동일 인스턴스 공식 obj.
> 측정: 공식 `../src/utils.check_feasibility`. 가설→검증→인사이트→파생 루프.

## 확정 사실 (기반)
- **정사영**: z2·z3 = 배정만의 함수. z1 = EXIT시각(타이밍). 패킹(x,y,o)=실현가능성전용.
- **패킹 밀도는 z1 레버 아님** (격리+동일 CP-SAT 타이밍서 wash, 2026-06-20 falsified).
- **레버 = 배정(z2/z3) + CP-SAT 타이밍(z1).** 전역그리디가 배정을, 오라클이 타이밍을.
- CP-SAT 오라클 `myalgorithm._cpsat_bay_timing_verified(prob_info, [Bay], results{bay:{bid:rec}}, deadline)` → 재타이밍 solution|None. infeasible 레이아웃도 재타이밍으로 살림.

## 기준선 (prob_38, @200s, w1=13333 w2=2 w3=300)
| | obj | z1 | z2 | z3 |
|---|---|---|---|---|
| 원래 솔버 | 87,743,911 | 6385 | 1653 | 8698 |
| 우리(전역그리디 CW=1 +CPSAT) | 92,008,030 | 6882 | 2762 | **816** |
→ 우리 −4.9% 패. **z3 압승(816 vs 8698)**, z1만 +497 밀림(w1 지배라 짐).

## 가설 원장
### H1 (폐기): 고정 CW 스윕
- 사용자 인사이트(2026-06-20): 인스턴스마다 w가 자릿수로 다름(w1 667~29.6K) → 고정 CW는 틀림. 배정은 *그 인스턴스 w*를 봐야 함. z1 프록시(load/area)가 지각단위가 아니라 w1 가중이 무의미했음.

### H1' (검증중): weight-adaptive 전역그리디 (CW 제거, tardy_est)
- z1 항 = area-time 혼잡 기반 지각 추정(시간 단위): i의 [R,D] 창에 겹치는 footprint 합이 베이면적 초과분 → wait → tardy_est. score = w1·tardy_est + w2·Δz2 + w3·Δz3. w1이 자동으로 weight-adapt.
- 실험: prob_38(w1=13333)·37(3333)·25(667)·40, @200s, 우리 vs 원래.
- 기대: 고-w1=혼잡회피(분산,z1↓), 고-w3=선호우선(z3↓). 인스턴스 무관하게 균형 잡혀 원래 추월/근접.
- 결과: **승 1/4.** prob_38(w1=13333) **승 +1.8%**(z1 6627≈원래6651, z3 3816 vs 8080). prob_37 −25.9%·prob_25 −48.5%·prob_40 −4.6% 패 — 전부 **우리 z1이 더 나쁨**(crude tardy_est가 작은/저-w1 인스턴스서 과적 오추정 → z1·z2↑).
- **인사이트**: z3 레버는 확실(모든 인스턴스서 z3 우리<원래). 약점은 **z1 제어**(crude proxy). weight-adaptive는 z1-지배 인스턴스서만 이김. → 실제 z1 평가가 필요.

### H2 (검증중): 원래의 z1-좋은 배정 시작 + obj-toss(실제 per-bay z1) → z3 끌어내림 + CP-SAT 타이밍
- 가설: 원래 배정은 z1 균형 좋음(but z3 나쁨). everyone-preferred 시작 + 전체-obj toss(w1·our_z1 + w2·z2 + w3·z3, 실제 packing z1)로 균형점 찾고, 마지막 CP-SAT 타이밍으로 z1 최적. crude proxy 대신 실제 z1.
- 실험: prob_38/37/25/40 @200, vs 원래.
- 결과: (대기)

### H3 (검증중, 사용자 본래 비전): 배정 단계 제거 — 통합 전역 그리디
- 핵심: 베이 선배정 X. 각 블록(EDD)을 *모든 베이*에 시도 → 그 베이 현 상태서 가장 이른 feasible 위치(v2 폴리곤+크레인+시간재사용)의 marginal obj 계산 → 전역 최소에 배치. 배정=emergent.
- 동기(사용자): 배정 선결정은 (1) z1 오추정, (2) 다른 베이 빈공간 못 씀. 통합 그리디가 둘 다 해결.
- H1/H2와 근본 차이: H1/H2=배정→패킹(2단), H3=배정·패킹 동시(통합). 그 위 CP-SAT 타이밍.
- 파일 `unified_greedy.py` + `ptiming.py`(병렬 per-bay 타이밍, 사용자 통찰 — 184s순차→45s병렬, prob_38 5분→73초).
- **결과 (one-at-a-time)**:
  - **prob_38(N=250,w1=13333): 승 +18.4%!** 74.34M vs 원래 91.11M. **z1·z2·z3 전부 H3가 낮음**(z1 5431<6651, z2 1412<2964, z3 6421<8080). 배정 안 하니 빈공간 활용→혼잡↓→z1 원래보다도 낮음. 73s.
  - prob_25(N=100,w1=667): 패 −10.9%(610K vs 550K). z2 몰빵(2263 vs 47, dist[61,39]). 단 H1(817K)보단 훨씬 나음.
- **인사이트**: 배정없는 통합 그리디가 **큰·고-w1서 압승**(z1 직접 개선). 작은·저-w1서 z2 몰빵으로 패. 패턴=w/크기 의존. 다음: prob_37·40 확인, z2 균형 보강.
- 주: 원래 legacy(baseline_greedy)가 개념상 이것(통합 그리디)인데, 원래는 T≥200서 gassign(배정먼저)을 씀. H3는 v2 폴리곤+통합을 명시.

### 파생 후보 (백로그)
- H2: 원래 배정(z1균형 좋음)에서 시작 + z3-toss(선호로 옮기되 CP-SAT z1 무악화 조건). 원래 z1 + 우리 z3.
- H3: z1 격차가 배정(과적)인가 패킹(v2 레이아웃이 타이밍에 불리)인가 — 동일배정서 v2 vs fastfloor 패킹 + CPSAT 비교(격리 실험 재활용).
- H4: 인스턴스 의존성 — w1/w2/w3 비율별로 CW 최적이 다른가 (weight-adaptive CW).
- H5: 전역그리디 z1-proxy 개선 — load/area 대신 실제 패킹기반 tardiness 추정.

---

## H6 (2026-06-20): 패킹 *순서·위치* 가 z1 레버 — 측정·반증·돌파 (prob_25 집중)

> 단일 진실: z1 은 timing 도 배정균형도 아닌 **베이 내부 배치(위치·순서)** 가 결정. 측정은 full obj·동일 TL.

**측정 정정 (중요)**: BASELINE dict 가 원래@**200** 값인데 실험은 @120 → 불공정 비교였음.
- 우리 파이프라인은 **~40초에 품질 plateau** (timing 156초 줘도 z1 불변 = timing 은 우리 layout 의 최적). 원래는 느려서 grind: prob_25 원래 @120=889K, @200=550K.
- ⇒ **TL≤~150 우리 승, TL≥~200 원래 승**(우리가 시간을 안 씀). 시간적응형 필요.

**반증된 레버 (재시도 금지)**:
- 배정 area-time 균형(cpsat_guideline 용량제약): z1 **악화** ([61,39]→[56,44] z1 844→972). 균형 ≠ z1.
- 토스(베이간 relocate): prob_25 **0 이동**(개선 0, 23초 낭비) → 측정오염. **기본 OFF**(`OGC_TOSS=0`).
- 접촉 **정확-면맞닿음(D=1)**: contact-max z1 844→**1020 악화**(과거 contact-area 반증과 일치).

**검증된 레버 (채택 후보)**:
1. **패킹 순서가 z1 2배 좌우**: edd 844 / release 1219 / area 1289 / height 1740 (전부 CP-SAT 타이밍 후). EDD 최선.
2. **타깃 순서 스왑**(`descent_tardy`): tardy 블록만 앞으로 당김 → 랜덤 descent 와 동급 z1 을 **8배 빠르게**(786@83s vs 777@652s). deadline 기반 시간적응형. ⚠ 비결정적(노이즈원).
3. **★near-접촉(D=2)이 반증을 뒤집음 (사용자 핵심통찰)**: 정확-맞닿음(D=1)은 노이즈→나쁨. **거리 D=2 이내를 접촉 인정**하니 contact-max 844→**778 개선**. D=3 은 너무 느슨(775, 더 나쁨) → **D=2 스윗스팟**.
4. **fit=tardy = top-K near-접촉 후보 → 크레인 안막는(쌓기 페널티 최소) 자리** (`OGC_FIT=tardy`): 778→**762**. 사용자 ③("먼저 나갈 애 위 안 덮기")이 D=2 에서 작동(D=1 단일레이어 prob_25 엔 쌓기 0 이라 무효였음).
5. 벽 접촉 가중치(`OGC_WALL_W`): **비단조**(1→+2.6% / 2→-16.5% / 3→+7.5%) = **노이즈/과적합 신호, 단일인스턴스 튜닝 금지**. 기본 1(중립=near-접촉 그대로).

**돌파 (prob_25, @120, orig 550,459)**:
| config | obj | z1 | 판정 |
|---|---|---|---|
| baseline (EDD first-BL, toss on) | 610,651 | 844 | 패 -10.9% |
| + 타깃스왑 0.5 | 571,965 | 786 | 패 -3.9% (plateau) |
| + near-접촉 D=2 fit=tardy (스왑X) | 555,957 | 762 | 패 -1.0% (25초 한패스!) |
| **+ 스왑 0.5 (WALL_W=1)** | **535,947** | **732** | **승 +2.6%** |
| + WALL_W=3 (노이즈) | 509,267 | 692 | 승 +7.5% (비신뢰) |

⇒ **레버 스택 = 토스OFF + near-접촉(D=2) + fit=tardy(크레인-안막힘) + 타깃스왑 → prob_25 -10.9%→승.**
신규 env: `OGC_FIT`(0|1|tardy) `OGC_CONTACT_D`(2) `OGC_WALL_W`(1) `OGC_PACK_SWAP`(TL비율) `OGC_TOSS`(0).

**일반성 검증 통과 (과적합 아님)**: prob_38 +18.4%→+25.8%, prob_37 +4.1%→+14.8%, prob_40 +11.1%. 4/4 승.

## H7 (2026-06-20): ★후보 다양화 + 오버랩 = 거대 도약 (사용자 핵심통찰 2연타)

> 단일 진실: 진짜 병목은 fit 선택이 아니라 **후보 생성**. BL-프론티어만 보면 베이 중간 gap·인터록 자리가 후보에 없어 선택이 무력. 전역 snug 후보를 띄우면 오버랩까지 살아난다.

**진단 (cand_diag.py)**: `_bl_candidates`가 "각 행 leftmost feasible"만 반환 → 후보가 bottom-left 프론티어 띠. 후보수 분포는 충분(94%가 2개+)이나 **전부 BL-frontier** → 베이 중간의 애매한 틈(snug gap)·인터록(z축 겹침) 자리가 후보에서 누락.

**Feature 1 — 후보 다양화 (`OGC_DIVERSE=1`)**: feasible 영역의 *경계 셀*(인접에 점유/벽 있는 snug 자리) 전체를 균등샘플 → 베이 전역 gap·코너·인터록 자리 포함. `_bl_candidates(diverse=True)`.
**Feature 1 효과 (prob_25 @120 swap off)**: fit=tardy z1 762→**651**, obj 555,957(-1.0%)→**481,920(+12.5%)**. 후보 다양화 *단독*으로 z1 −15%.

**오버랩 부활 (`OGC_FIT=ov` = 접촉+오버랩)**: 이전(BL-frontier)엔 fit=ov 무효였음 — *인터록 자리가 후보에 없어서*. diverse 켜니 인터록 자리가 후보에 떠 오버랩 보상(`_overlap_value`: GOOD nest +20 / BAD 임박덮기 −50)이 작동: 651→**634**, **+14.5%** (스왑 없이 28초).

**일반성 (diverse=1 fit=ov swap off)**:
| | 이전스택 | diverse+ov | z1 |
|---|---|---|---|
| prob_25 | +2.6% | **+14.5%** | 762→634 |
| prob_37 | +14.8% | **+28.6%** | 2045→1606 |
| prob_38 | +25.8% | **+34.4%** | 6651→4338 (91M→59.8M) |

⇒ **검증 스택 = 토스OFF + near-접촉(D=2) + ★diverse후보 + fit=ov(접촉+오버랩) [+ 스왑].**
신규 env: `OGC_DIVERSE`(1) `OGC_DIVERSE_LIM`(40) `OGC_FIT=ov` `OGC_OVERLAP_W`(20) `OGC_OVERLAP_BAD`(50).

**4/4 확정 (diverse+ov swap off)**: prob_25 +14.5%, prob_37 +28.6%, prob_38 +34.4%, prob_40 +20.2%.

### H8 (2026-06-20): 강제 인터록(결합블록) 반증 + 속도 단축

**Feature 2 강제 인터록 페어링 — 반증**: `merge.py` 래스터 페어링(1.4s, shapely→numpy 100배)으로 인터록 쌍 탐색
(prob_25 16쌍/32블록, overlap max 322셀). `simulate(pairs=...)` 로 base+partner 강제배치. **결과 prob_25
470,581→741,383(z1 634→1040) 대악화.** 이유: ① overlap *면적* 최대화 ≠ z1 이득 ② nest 강제로 B.exit≤A.exit
타이밍 결박 → tardy 폭발 ③ base를 partner 앞에 재정렬해 EDD 붕괴. **교훈: diverse+ov 그리디는 인터록을
*선택적*(이득될 때만)으로 하는 게 우월. 강제 금지.** OGC_MERGE=0 기본 OFF 격리(코드·인프라 보존). 오버랩 보상
가중(OGC_OVERLAP_W 20/60/150)도 *포화*(동일) — 인터록 *기회*가 한계지 보상세기가 아님.

**속도: per-bay 타이밍 무캡 → 베이크기 비례 캡** (`cap = 15 + 0.5·max_bay_blocks`, `OGC_TIMING_CAP` override).
무캡(~136s/bay)은 CP-SAT 노이즈로 *더 느린데 더 나쁨*. 캡 검증(4/4): prob_38 196→127s(z1 4337, 동일),
prob_37 90→69s(+28.8%), prob_40 196→144s(+21.4%), prob_25 27s(동일). **품질 유지·25~35% 단축.**

**계측 인프라**: `OGC_STAGES`=단계별 시간·z 기록(unified.STAGES) · `report_data.py`=리포트 데이터 JSON 덤프
· `pipeline_report_v2.html`=단계별 시각 분석(부하막대·후보맵·베이 top-view·간트, ui-designer 작성)
· `cand_diag.py`=후보 위치/개수 진단 · `merge.py`=인터록 페어링(격리).

### H9 (2026-06-20): ★오버랩 불안정(정정) + ★★id-캐시 멀티인스턴스 크래시 버그

**오버랩(fit=ov) 정정 — 신뢰할 레버 아님**: fit=1(접촉-max, 오버랩無) vs fit=ov 격리 A/B(diverse, @200):
prob_25 ov우세(+14.5 vs +11.2)·**prob_37 fit=1 우세(+34.4 vs +28.8)**·prob_38 무승부(34.8/34.2)·**prob_40
fit=1 우세(+22.1 vs +17.8)**. ⇒ **오버랩은 instance-dependent, 평균 wash~음(-).** "diverse+ov가 다 이김"은
*diverse+접촉*이 한 일이지 오버랩 아님. 인터록(merge·overlap 둘 다)은 신뢰할 레버 아님 확정. **로버스트 기본
= fit=1(접촉-max)+diverse.** (혼잡 시점도 ov=0 후보 많음 = 인터록 기회 희소.) 진단: cand_diag ov 통계.

**★★ id-캐시 크래시 버그 (치명적, 수정)**: `unified._CM`(id(sh))·`temporal_pack._FPC`(id(cmasks))가
*모듈 전역*인데 인스턴스 간 미초기화 → 인스턴스1 shape GC 후 인스턴스2가 같은 id 받으면 stale mask 반환
→ "list index out of range" 크래시. **단일프로세스 멀티인스턴스서 34/40 크래시**(개별 프로세스론 정상이라 못
봤음). **평가서버가 한 프로세스서 algorithm() 여러 번 부르면 똑같이 터질 실버그.** 수정: `unified()` 시작에
`_CM.clear(); _tp._FPC.clear()`. (density_pack/build_set의 cm 캐시는 함수-로컬이라 안전.)

**ALL40 @120 검증**: 진행중(run_all40.py, fit=1). set1=이 v2 첫 시도. 총obj·set1/set2·feasibility(절대−1).

### H10 (2026-06-20): ★★ALL40 검증 + 2대 버그 픽스 + 제출 준비

**ALL40 @120 (fit=1+diverse+near-접촉+캡):**
- 1차: feasible 6/40 (id-캐시 크래시 34) → **id-캐시 fix(unified `_CM.clear()`+`_tp._FPC.clear()`)** → 37/40.
- 잔여 3개(prob_3·9·14) **stage-5 실현불가**: overhang 스택의 크레인 EXIT 순서 위반(`EXIT block A obstructed by B(sweep)` = B가 A 위에 얹혀 A 못 나감 → 연쇄). 비결정적.
- **★ NOSTACK 픽스 (`OGC_STACK` 기본 off = allow_stack=False)**: overhang 스택 금지 → **40/40 feasible, 0 −1**. 게다가 set1 obj/z1 *개선*(prob_1 591→474K, prob_4 806→631K) — 스택은 feasibility 깨고 obj도 악화. 인터록이 z1 레버 반증된 것과 일관.
- **최종 ALL40: 40/40 feasible, 총 239.27M (set1=13.96M, set2=225.31M).**

**원래 솔버 대비**: set1 v2 13.96M ≫ 원래 ~1.4M(원래 z1=0 압승) / set2 v2 225.31M < 원래 ~272M(v2 ~17% 승).
⇒ **best-of(원래 set1 + v2 set2) ≈ 227M** 최강. v2 단독은 set1 약점(z1>0 vs 원래 z1=0).

**v2 제출 비호환 발견**: ptiming 워커가 `inst`(파일경로)를 subprocess서 re-load → 서버선 prob_info 직접전달(파일無). 해결: prob_info를 실행폴더 temp JSON으로 쓰고 경로 전달. + 모든 `sys.path.insert(../src)` 제거 필수.
**v2 의존**: `from myalgorithm import _cpsat_bay_timing_verified`(원래 src/) → 제출엔 원래 솔버 전체 번들 필요.

**다음**: 제출 zip 구조 결정 (원래-safe / best-of / v2-guard) → 패키징 → 로컬 서버-모사 테스트 → zip. 리포트 정정(오버랩 instance-dependent).
