# Overnight moveall-lever experiment plan — 2026-06-24

> 자율 순차 실행. 러너 `_overnight_runner.py` → 로그 `_overnight.log`, 결과 누적 `_overnight_ledger.md`.
> 판정 규칙(사용자): 검증=full set, 판정=개별 z 아니라 **총 obj** + **never−1 최우선**. 답지 튜닝 금지.
> 모든 신규 게이트 기본 OFF → 프로덕션(`myalgorithm`) 경로 무영향. 이 실험은 **testbed 격리**.

## 중심 질문 (CENTRAL)
moveall 계열에 **수렴해(CONV = 프로덕션 동치, 인라인 moveall 이미 돈 뒤)** 위에서
총 obj 를 robust 하게 깎는 강화가 존재하는가?
- YES (CONV 에서 Δobj↑, accepts>0, 여러 인스턴스 일관) → 아침에 `_run_loop` 인라인 moveall 을
  `_moveall_pass` 호출로 교체(또는 해당 게이트만) → **full ALL40 A/B + never−1 확인** → 채택.
- NO (CONV 에서 ~0) → moveall = 천장. 피벗: per-bay 패킹밀도(root, 난이도↑) 또는 never−1 검증·제출 굳히기.

배경(직전 세션): 크로스베이 front/cluster 전부 falsified(분산 레버리지 + 만석 벽). moveall(집중
레버 = 늦은 블록 *자체*를 이동)이 더 낫다 → moveall 강화로 피벗. 벽 = per-bay 패킹밀도(만석 베이는
크로스베이 갈 데 없음). prob_38/33 포화, prob_33 완전포화.

## 강화 노브 (postproc.py `_moveall_pass`, 전부 call-time gated)
- `OGC_PP_MOVEALL_PREF=1` — bt 의 PREFERRED 베이 우선(z1+z3 동시이득) 후 나머지 점유면적순.
- `OGC_PP_MOVEALL_DESTRETIME=1` — bt + 목적지의 co-present 블록까지 free → 목적지가 RE-TIME 해 bt 흡수
  (frozen-dest baseline 이 포화 베이서 못 푸는 무브).  ← **핵심 가설**
- `OGC_PP_MOVEALL_ORDER=tardy|area|copres` — tardy(기본, worst-first) / area(최대 bbox 우선) /
  copres(베이내 co-present 최다 우선).  60s 예산 내 어떤 무브를 먼저 시도할지만 바꿈.
- baseline(PREF=0, DR=0, ORDER=tardy) == 인라인 production moveall.  전부 never-worse 게이트.

## 가설
- **H1 (destretime saturation-break)**: `+destretime` 이 frozen-dest baseline 이 못 찾는 무브를 찾는다.
  특히 CONV 위에서(인라인 moveall 이 이미 돈 뒤에도 추가로 깎으면 = saturation 돌파 = 진짜 가치).
- **H2 (pref z3-win)**: `+pref` 가 선호 베이 우선 시도로 z3 동시 이득 → CONV Δobj↑(또는 z3↓ at z1 동률).
- **H3 (ordering)**: worst-tardy-first 가 최적 선정이 아니다 — area/copres 순이 60s 내 더 많은/큰 accept.
- **H4 (budget)**: destretime 가치는 예산-게이트 → 60s→120s→180s 로 accepts/Δobj 가 단조 증가하면
  in-loop(매 라운드 반복)에서 더 큼.
- **H5 (loop/saturation)**: `+destretime` 를 CONV 에 반복(3×60s) 적용 시 pass-2/3 도 accept 를 더 찾으면
  인라인 대비 누적 가치 있음 = 루프 배선 정당. 1패스 후 0 이면 in-loop 가치 제한적.
- **H6 (density floor, 피벗 진단)**: CONV 해의 per-bay 면적 utilization(peak concurrent area / bay area)
  이 ~100% 면 벽은 진짜 밀도(패커 교체만이 레버), <<100% 면 크레인 직렬화(타이밍/배치 레버 여지).

## 실험 큐 (순차)
대상: **FULL = [38, 33, 30]** (full matrix, v2 캐시 존재) + **GEN = [29, 25]** (generality, v2 빌드 필요).

각 인스턴스: raw v2 sol 로드/빌드 → CONV 1회 converge(~500s, 캐시 `out/_convsol_{inst}.json`) → 변형 실행.

FULL 인스턴스:
1. **EXP1-RAW** (order=tardy, 60s): baseline / +pref / +destretime / +both  ← H1·H2 raw 신호
2. **EXP1-CONV** (order=tardy, 60s): baseline / +pref / +destretime / +both  ← **H1·H2 핵심**
3. **EXP2-CONV budget** (+destretime, order=tardy): 120s / 180s  ← H4
4. **EXP3-CONV ordering** (baseline pref=0 dr=0, 60s): order=area / order=copres  ← H3
5. **EXP4-CONV iterate** (+destretime, order=tardy, 60s ×3 누적)  ← H5
6. **density diagnostic** (CONV 해, read-only)  ← H6

GEN 인스턴스 (시간 절약 위해 CONV 만):
- **EXP1-CONV** (order=tardy, 60s): baseline / +destretime  ← H1 generality
- density diagnostic  ← H6 generality

## 판정 휴리스틱 (러너가 SUMMARY 로 기록, 최종 판정은 사람)
- CONV 에서 `+destretime`(또는 +both/+pref) 의 Δobj 가 baseline 대비 **여러 인스턴스에서 일관되게 양수 +
  accepts>0** → H1 지지 → 아침에 루프 배선 + ALL40 A/B 후보.
- CONV 에서 전 변형 ~0(accepts 0) → moveall 천장 확정 → 피벗(density H6 진단 결과로 방향 결정).
- ordering(EXP3) 이 baseline 보다 CONV Δobj↑ → 선정 개선이 직교 레버.

## 안전/제약
- env python 직접(`conda run` 금지, 4-worker CP-SAT 크래시). cpu_affinity [0,1,2,3].
- 실험끼리/실런과 **병렬 금지**(오버서브 → 타이밍 오염). 러너가 단일 프로세스 순차 실행.
- 각 변형/인스턴스 try/except → 한 실패가 밤 전체를 죽이지 않음. 결과는 변형마다 즉시 ledger append.
- 프로덕션 채택/제출 변경은 **아침에 사람 승인 후** (CONV 증거 + ALL40 A/B 본 뒤). 밤엔 증거만 모은다.
