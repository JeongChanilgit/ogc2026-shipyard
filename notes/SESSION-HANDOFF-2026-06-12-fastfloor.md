# SESSION HANDOFF — z1=0 GOAL 엔드게임 v2 (2026-06-12, 스테이지트레이스 세션 갱신)

> **단일 소스 핸드오프.** 새 세션이 prob_14/20 마지막 마일을 이어가기 위한 진입 문서.
> 이전 버전(fastfloor 초기·§5 수리루프강화 임무)은 이 문서로 대체. 깊은 이력은 메모리
> `ogc2026-stagetrace-budget-breakthrough` · `ogc2026-z1repair-cap-results` 참조.

---

## 0. 30초 요약 (지금 어디인가)

> **★ 2026-06-13 갱신 — 제출 default 승격 완료.** 그동안 실제 제출경로(env 미설정)는 **legacy greedy-floor**였고 검증된 gate200_v2(fastfloor+banrace)는 전부 env-gated OFF였음. `OGC_SUBMIT_V2`(default ON) 마스터 스위치로 gate200_v2 16노브를 `algorithm()` 진입부에서 T≥60 적응 주입 → **full-20 @200 vs legacy: total obj 2.68M→1.55M(−42%)·paired z1=0 15→19/20·feasible 20/20**, 이전 tardy 5개(11/13/14/17/18) 전부 z1=0. 가역 `OGC_SUBMIT_V2=0`. byte-identical 속도레버 3개(FAST_GEOM/PP_RASTER/REDECODE_FAST)는 prob_20 추첨 악화로 제외(env-gated 유지). 잔여 회귀 prob_15 +34%. 메모리 [[ogc2026-submit-profile-promoted]]. **다음 목적함수 레버 = z3race@600**.

- **GOAL**: tl=100에서 full-20 전부 z1=0 (`_capture20_aff.py` ×2 paired).
- **현재 (@100, gate_v3 ×2 확정 — 오늘 코드 전부 포함)**: **paired z1=0 = 18/20 유지(회귀 0)** + **prob_14 3/3→2/2** + **prob_20 10/16→8/8 (변동 소멸)** + total obj 1.62M→1.58M.
- **잔여 2개**: prob_14(z1=2 결정적), prob_20(z1=8 안정) — 둘 다 **pp 무브로는 못 깎는 배정(assignment) 수준 한계**에 도달 (§4).
- **세션 핵심 발견 2가지**: ① 기존 18/20 채택구성에서 **z1_repair 루프는 한 번도 발화한 적이 없었음**(예산 기아; 18/20은 전부 cap의 몫). ② 그런데 발화시켜 보니 **루프는 z1 2~20 고원에서 예산 무관 채택 0인 budget-filler 세금**(@300에서 107~123s 무채택; OFF 시 obj −13K). 루프의 가치는 재앙 floor(z1 60+) 수리 보험뿐.
- **@300 고점("시간 많이 주면?")**: BAN-RACE 이전 파이프라인은 ~100s 포화(ceiling_300_r1: +0.2%). **BAN-RACE 도입 후 @200이 신규 기준**: gate200_br90 = total obj **−12.2%**, prob_14 paired 0/0, prob_20 7/1(187K). 메모리 `ogc2026-longtl-ceiling-2026-06-12`.
- **사용자 목표 "@200 전부 z1=0 + z3 최소" 최종 현황 (2026-06-13)**: **paired z1=0 19/20 달성** (gate200_v2, 회귀 0, obj −4.3%). 잔여 = **prob_20 z1=7/7 단 하나** — bay1 직렬큐의 ban 재빌드 floor 추첨({3..18})이 ≤3을 페어로 못 뽑음. z1=1 도달 런 2회 존재(187K·190K) → 다음 킬러 = 그 경로의 재현화(재빌드 floor 추첨 결정화) 또는 @300+ ROUNDS 증가.

## 1. 채택 확정 구성 (gate_v2, full-20 ×2 검증 2026-06-12)

```
OGC_FASTFLOOR=1
OGC_FF_PRIMARY=1
OGC_FASTFLOOR_MIN_T=60
OGC_FASTFLOOR_FRAC=0.20
OGC_CHEAPER_STEPS=0
OGC_Z1_REPAIR_LOOP=1
OGC_FF_ASSIGN_CAP=0.85
OGC_FF_PRIMARY_Z1MAX=150      # ★ 신규 — ff-primary 항상 고정(분기 제거)
OGC_CUMLEVEL_BUDGET_PCT=30    # ★ 신규 — cum_level 예산 70%→30%
OGC_Z1_REPAIR_RESERVE_S=25    # ★ 신규 — repair 루프 보장 창
OGC_Z1_REPAIR_TRIES=3         # ★ 신규 — best-of-N(시드순환+마지막 try 비결정 풀파워)
```
- 신규 4개 모두 env-노브 → 미설정 시 제출 경로 bit-identical (RESERVE/TRIES는 default OFF 코드, Z1MAX/CUMLEVEL은 기존 노브 값 변경).
- 게이트 증거: `results/capture/gate_v3_r1/ r2/`(최종, 오늘 코드 전부 포함) ≡ `gate_v2_r1/ r2/` vs `gate_rc_r1/r2`. 비교기 `notes/_gate_compare.py`.
- prob_12(+24.5K)·prob_6(+2.7K) 플래그는 **변동으로 직접 증명**: 단독 A/B(p12_rc/p12_v2)에서 rc·v2가 obj 119,049로 완전 동일, prob_6은 v2_r2=rc_r1=93,111 동일값. prob_12 밴드=104~129K.
- 참고: @100에서 RESERVE/TRIES(루프 강화)의 측정 기여는 0 (E1 단독런=게이트 결과 동일 — 주역은 Z1MAX+CUMLEVEL). 게이트 검증치 보존을 위해 구성은 그대로 두되, 단순화하려면 재게이트 후 제거 가능.

### @200+ 채택 확정 구성 (★★BAN-RACE v2 — 게이트 gate200_v2_r1/r2, 2026-06-13)
```
위 @100 구성에서 OGC_Z1_REPAIR_LOOP·RESERVE_S·TRIES 제거 (고원 세금)
+ OGC_FASTFLOOR_S=30 + OGC_XBAY_MAX_S=30
+ OGC_BAN_RACE=1 + OGC_BANRACE_S=90 + OGC_BANRACE_FF_S=30 + OGC_BANRACE_MIN_T=150
+ OGC_BANRACE_ROUNDS=2 + OGC_BANRACE_TAIL=1
```
- **★★최종 게이트 결과: paired z1=0 19/20 (18→19), 회귀 0건, total obj −4.3%.** prob_14 0/0(obj 104,881 — @100 z1=2짜리 대비 −10K), prob_12 −24.2K·prob_13 −8.7K·prob_20 7/7(−25.9K). 잔여 = prob_20 z1=7뿐.
- **ROUNDS=2**: 패배 라운드는 floor 불변 → 같은 ban 세트 재추첨(실패 확률 지수 감소; prob_14 paired의 결정타). **TAIL**: tardy ≤4일 때만 크레인-꼬리(같은 베이 후행 exit 2개/블록) 추가 ban — prob_14의 블록-64형 정체 해소; 대형 tardy군(prob_20)엔 자동 스킵(과스프레드 방지).
- **★BAN-RACE = 이 세션 최종 아키텍처** (T1 race 패턴 재사용): 메인 pp가 z1>0으로 끝나면 plain floor의 실현 tardy_map을 ban으로 fastfloor 재빌드 → **자체 풀 pp** → strict-< 최종-대-최종 승격. 런당 결과 = max(plain, ban); 깨끗한 인스턴스 비무장.
- **br90 게이트 결과**: paired z1=0 18/20 + **prob_14 paired 0/0(obj 109,506 — @100의 z1=2짜리보다 낮음)** + prob_20 7/1(obj 187,507 역대최저) + **total obj −12.2%**. 결함 prob_18 4/0(1런; w1 작아 obj +2.3K뿐).
- **잔여 한계 = 추첨 복권**: @200 단일런 z1=0 18~19/20, 실패는 12/14/18/20 회전(1~7 단위, ff floor·pp 추첨). 게이트 3종(S=70/S=90/Z1MIN=5) 비교로 확인 — Z1MIN=5는 18 고치고 12·14를 깨므로 기각(`OGC_BANRACE_Z1MIN` env만 잔존, 기본 1.0=br90).
- 이르게 된 길(전부 실측 기각, 재시도 금지): ff-레벨 정적 가드(Z1MIN/BAN_DELTA/가드리스) · pp-레벨 재빌드 훅(불공정 비교+기아) · per-bay 캡(전이) · @100 모든 ban 형태(예산 부족 — 정찰+재빌드 25~30s+pp가 100s 불가). 교훈: **닫힘성은 정적 레벨에서 예측 불가 — 최종-대-최종 레이스만 옳다.** ban 빌드당 ~30s 필수.
- **prob_20 마지막 추가 시험 (2026-06-13, 전부 추첨 밴드 내 = 기각)**: z1 repair 루프 재활성(경량 RESERVE15/TRIES1) → 13/8, `OGC_T5_CANDS=1`(pp insert 폴리곤 후보) → 14/7. **잔여 z1의 정체 갱신**: 채택해(v2_r2, z1=7)의 tardy는 bay1이 아니라 **bay2(153×15 얕은 베이) 잔챙이 4개 + bay3 1개, 각 1~2단위** — 런마다 잔여 베이가 바뀜(추첨).
- **경쟁자 프로필(notes/competitor-2026-06-11.json prob_20)**: **z1=0, z3=463, z2 5536.89(희생!), 47초.** w2=6이라 z2 희생은 +23K뿐인데 z3 −132K — 그리고 47초 만에 z1=0이면 **디코드 코어가 구조적으로 우위**(탐색이 아니라 구성 휴리스틱).
- **★다음 세션 빌드 스펙 — "prob_20 z1=0 디코더" (경쟁자 프로필이 존재 증명)**:
  1. **per-bay 디코드-용량 캘리브레이션 루프**: 빌드의 per-bay 실현 ft_tard로 cap_alpha_j를 베이별 보정 후 재배정·재디코드 (ban의 원리화 — 블록 ban 대신 베이 용량 학습; 얕은 bay2는 낮게, 깊은 베이는 높게).
  2. **exit-순서 인지 적층 (anticipatory)**: `_ft_search_pos`(fastfloor:231)가 첫 feasible BL 스팟을 반환하는 구조 → 후보 채점에 "늦게 exit하는 블록은 deep/비차단 위치, 미래 블록 창과 footprint 겹침 최소화" 항 추가. 문헌 인사이트(`ogc2026-z1-lever-is-packing` 문헌리뷰 anticipatory배치)와 합치.
  3. **ff 디코드에 폴리곤 후보 합류**: 현재 abut 후보가 bbox(pbox) 모서리만 — T5 column-drop을 `_ft_search_pos` 후보 생성에 머지(폴리곤 맞물림 위치).
  4. 배정 모델 z2 완화 실험: 경쟁자처럼 z2 희생 허용(w2=6 → 사실상 공짜).

## 2. 이번 세션 구현물 (전부 src/myalgorithm.py, env-gated)

1. **`OGC_Z1_REPAIR_RESERVE_S`** — pp에 `_up_dl = deadline - reserve` 도입. 루프 무장 + pp 진입 z1>0일 때 상류 전부(cum_level/cpsat_timing/bbox/crossbay/cheaper/legacy single-move apply)를 `_up_dl`로 당김. 루프·Front B는 full deadline → 예약은 루프 실패 시에도 Front B로 환류.
   - 함정(이번에 두 번 데임): 상류 하나만 당기면 **다음 budget-filler가 그 시간을 흡수**한다 (cum_level→crossbay→legacy apply 체인). 전부 당겨야 함.
2. **`OGC_Z1_REPAIR_TRIES`(+`OGC_Z1_REPAIR_WILD` 기본1)** — 루프 (a)retime/(b)repack을 try마다 시드 바꿔 N회, 마지막 try는 `OGC_DEV_DET` 해제(멀티워커 풀파워). consider() 단조 → 회귀 불가. try마다 deadline 가드.
3. **`z1_repair_swap` (c2 스텝, `OGC_Z1_REPAIR_SWAPS`=24)** — relocate 불가(전 베이 포화) tardy 블록을 타깃 베이 high-slack 파트너와 1:1 교환. `_fb_swap_sol` 미러(fixed-others 삽입 2회). **prob_14에서 채택 0** — fixed-others로는 실현 불가 확인(§4).
4. **계측 인프라** — `notes/_capture20_aff.py`가 per-instance `.stdout.txt`/`.stderr.txt` 덤프(기존 DEVNULL 폐기 수정). **계측은 전부 stderr로 나감**(핸드오프 구버전의 "stdout" 표기는 오류였음). 요약기 `notes/_stage_summary.py <tag> <inst...>`, 게이트 비교기 `notes/_gate_compare.py`.
5. **고점(@300) 추가 구현** (전부 env-gated, default 불변):
   - `OGC_FF_TRIES` (myalgorithm ff 호출부): 독립 풀빌드 best-of-N — (z1,obj) 최소 채택, 예산 N분할. prob_20 floor 양봉(36↔62) 대응의 정답 모양.
   - `OGC_FF_REDECODE` (fastfloor 4d, T≥30만 무장): worst-베이 재롤. 실측 약함(gain 0~1) — OFF 권장. 부수효과로 `_fixed_time_decode`가 명시적 순서 리스트 수용.
   - `OGC_XBAY_MAX_S` (pp crossbay 절대 캡) / `OGC_Z1_REPAIR_RESERVE_PCT`(예약 비율화 — **해로움, 금지**).
   - c2 swap에 **eviction 체인**(파트너→제3베이 폴백) — prob_14/20 고원에서 실현 0건(전 베이 포화) 확인됨.

## 3. 왜 이게 통했나 (멘탈모델 갱신)

1. **z1_repair는 위치상 마지막인데 상류가 전부 budget-filler** → 기존 채택구성에서 발화 0 (STAGE_TIMING으로 증명: prob_14 cum_level 51s 채택0, prob_20 greedy floor 41s 낭비). 루프 강화(§5 구버전)보다 **예산 재배분이 선결**이었다.
2. **prob_20 변동(6~18)의 주범 = `OGC_FF_PRIMARY_Z1MAX=35` 경계 분기.** ff floor z1이 15/16/26/43/>60으로 출렁 → 35 초과 런만 greedy floor(41s, 결과 z1=96·z3=4146으로 더 나쁨) 경로로 추락. Z1MAX=150으로 분기 제거 → 8/8 안정.
3. **prob_20 최종 z1 ≈ ff floor z1 − 8.** (floor 15/16→최종 7/8, 26→16.) 남은 레버는 pp가 아니라 fastfloor floor 품질·변동.
4. repair가 못 깎는 인스턴스에서 reserve+tries ~25s는 z3 세금 — 단 legacy apply까지 당겨놨고 Front B가 환류받아 실측 피해는 가벼움(prob_14 obj는 오히려 세션 최저 114.9K).

## 4. 잔여 2개의 근본원인 (실측 확정)

- **prob_14 z1=2** (결정적 재현, E2/E3/E5 동일): `notes/_tmp_p14_analysis.py`
  - block 64(bay3): 동거 10개 중 6개가 더 늦게 exit → **크레인 직렬화 1단위**. 베이 공간은 있음(65%).
  - block 211(bay2): 이상 창 [27,36]에서 **전 베이 86~153% 포화** → relocate 불가, swap도 fixed-others 삽입으로는 슬롯이 안 나옴(채택 0).
  - 닫으려면: 전역 타이밍 재조정(여러 베이 동시 re-time), eviction 체인(파트너를 제3 베이로), 또는 다른 배정.
- **prob_20 z1=8**: bay1(928, 33블록 351%, 62블록 top-pref) 직렬큐가 단일베이 LB에 도달 — retime/repack LB-skip, reloc/swap 타깃 포화. 최종 z1 = ff floor − 8 관계이므로 **floor 자체를 낮추는 게 유일한 큰 레버**.

## 5. 다음 임무 후보 (우선순위 — @300 고점 실험 반영 갱신)

1. **배정 수준 다양화 (z1=0 완주의 유일한 남은 큰 레버)** — prob_20 bay1 직렬 LB≈8은 이 z3-최적 배정의 고유값. 인스턴스 적응 per-bay alpha(bay1만 타이트) 또는 강제 스필. w1=26.7K → z1 8 제거=+213K vs z3 +500 손실=−66K → **순익 ~150K** 여지. (시도·기각된 것: eviction 체인/swap — 전 베이 포화로 실현 0건, repack/retime — 단일베이 LB 도달, 시간 증액 — floor 추첨에 막힘.)
2. **prob_14 마지막 2**: 전역 동시 re-time — longtl_300에서 race-pp cum_level이 1회 z1=1을 뚫었음(비재현). 그 경로(재디코드+넓은 cum_level)의 재현화. 단일베이 수단은 전부 소진 확인.
3. **ff best-of-N 강화**: try당 20~30s 유지하며 N 증가(@600+에서 FASTFLOOR_S 더 키우기), 또는 디코드 분지(36↔62 양봉)의 구조적 결정화.
4. @300 권장구성(§1) full-20 ×2 게이트 → 채택 확정.
5. 채택구성 default ON 승격 판단(제출 경로) + z1=0 후 잉여시간 z3 본게임 (`ogc2026-goal-beat-competitor-600s`).

## 6. 측정 — 반드시 지킬 것 (불변)

- **하니스는 `notes/_capture20_aff.py`만** (원본 `_capture20.py` 오염 미수정, 사용 금지). 캡처 2개 동시실행 금지(코어마스크 충돌) — 순차로.
- **판정은 full-20 ×2 paired** (`ogc2026-validate-full20`). 단일런=선별용. **prob_12/6류 obj 플래그는 변동 밴드 확인 후 판정** (§1 사례).
- 스테이지 트레이스: env에 `OGC_STAGE_TIMING=1,OGC_Z1_TRACE=1` 추가 → `<tag>/<inst>.stderr.txt` → `notes/_stage_summary.py <tag> <inst>`.
- 실행 예:
```
ENV="OGC_FASTFLOOR=1,OGC_FF_PRIMARY=1,OGC_FASTFLOOR_MIN_T=60,OGC_FASTFLOOR_FRAC=0.20,OGC_CHEAPER_STEPS=0,OGC_Z1_REPAIR_LOOP=1,OGC_FF_ASSIGN_CAP=0.85,OGC_FF_PRIMARY_Z1MAX=150,OGC_CUMLEVEL_BUDGET_PCT=30,OGC_Z1_REPAIR_RESERVE_S=25,OGC_Z1_REPAIR_TRIES=3"
C:\Users\peter\anaconda3\envs\ogc2025\python.exe notes/_capture20_aff.py --instances ALL --timelimit 100 --tag <tag> --env "$ENV"
```
- conda env = **ogc2025**. 인스턴스 = `instances/train/prob_1..20.json`.

## 7. 데이터 — 무엇이 어디에

- 게이트: `results/capture/gate_v2_r1/ r2/` (채택, ×2) vs `gate_rc_r1/ r2/` (직전 채택). 진단 트레이스: `stagetrace_d1`(채택구성 발화0 증명), `_e1p14/_e1p20/_e2/_e3/_e4a/_e4b/_e5`(실험 체인), `p12_rc/p12_v2`(변동 증명).
- 분석 스크립트: `notes/_stage_summary.py`(스테이지 요약) · `notes/_gate_compare.py`(paired 비교) · `notes/_tmp_p14_analysis.py`(prob_14 잔여 구조).
- 통합 테이블(구버전): `results/z1zero_2026-06-12_per_instance.csv` — gate_v2는 미반영.

## 8. 핵심 파일 / 수정금지 (불변)

- 작업: `src/myalgorithm.py`(제출 엔트리), `src/fastfloor.py`(초기해). **수정금지**: `src/utils.py`, `baseline/` 전체.
- 시그니처 불변: `def algorithm(prob_info: dict, timelimit: float) -> dict`.

## 9. 관련 메모리

- `ogc2026-stagetrace-budget-breakthrough` — 이번 세션 진단·구현·결과 (단일 소스).
- `ogc2026-z1repair-cap-results` / `ogc2026-w1-diagnosis-z1zero` / `ogc2026-goal-z1zero-100s` — 직전 이력.
- `ogc2026-capture-harness-poisoning` / `ogc2026-validate-full20` / `ogc2026-z3-variance-2026-06-10` — 측정 규칙.
