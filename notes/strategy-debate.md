# OGC 2026 풀이 전략 — 3-에이전트 토론 결과

**일자** : 2026-05-28
**참여** : The Theorist (수학적 통찰) / The Pragmatist (대회 운영) / The Contrarian (반대자)
**진행** : Round 1 (독립 초안) → Round 2 (상호 공격) → Round 3 (수정·최종 입장)
**목표** : 다른 사람이 클로드를 썼을 때 나오는 *평균 답변* 과 차별화된, *이 문제·이 점수공식·이 평가환경* 에 특화된 전략 도출

---

## 0. 문서 사용법

- §1 은 토론의 *진화* 를 한눈에 보여주는 다이제스트. 본선 D-1 에 다시 펴 봐도 답이 나오게.
- §2 는 세 페르소나의 *최종* 입장을 보존 — 의견이 갈리는 부분은 갈린 채 둔다.
- §3 은 *합의된* 결정사항. 점수 0순위, 무조건 한다.
- §4 는 *의도적 분기*. 실험으로만 결판날 항목. 메인 컨텍스트가 임의로 합의시키지 않는다.
- §5 는 *즉시 실행할 액션*. 6월 1주차에 끝낼 작업 목록.

---

## 1. 토론 진화 다이제스트

세 에이전트가 라운드를 거치며 진화한 모습 :

| 라운드 | Theorist | Pragmatist | Contrarian |
|---|---|---|---|
| **R1** | HIPS 3-layer (LP-MIP → NFP → Lagrangian dual) | S0/S1/S2 게이트 + Best-of-K seed + fallback chain | 5-페르소나 (Topology-MIP / Lex Z1=0 / Anti-EDD / Reverse-time / EDD++) |
| **R2 자기진화** | NFP lazy 캐싱 / Layer 1 aggregate spatial cut / dual step instance-class-conditioned | "게이트는 floor, 페르소나는 ceiling" / Topology-MIP 을 K=4 한 자리에 수용 | 슬롯-MIP 가 *최종 좌표 아닌 순서만* 결정 / 페르소나는 *대회 기간 따라 진화* |
| **R3 결정타 받음** | Contrarian → "HIPS도 평균답변 변종" (정통타격) | Contrarian → "R−nb 기하학 오독" (산술 정정 강제) | Pragmatist → "실험비용 폭발" (페르소나별 검증 포기 강제) |
| **R3 진정한 직교** | Phase 0 probe (알고리즘 자가진단) + dual = search direction compass | 인스턴스 점수 산술 정정 → S2 "feasibility 유지 시 무조건 push" | R−nb 우측 비대칭 *명시적 게임이론* + *의도적 포기* 알고리즘화 |
| **R3 자가점검** | "절반만 다르다" 정직 인정 | "평균답변 공학화였다, R3 에서 일부 진화" | "R1 5페르소나는 평균 + 표면차별화였다 → R3 에서 2점 직교 살아남음" |

세 명 모두 *최초 라운드 입장의 약 50~70% 를 양보* 했고, *각자 1~2개의 진정한 직교 각도만* 남았다. 그 살아남은 직교 각도가 *우리 차별화의 본체* 다.

---

## 2. 페르소나별 최종 입장 (Round 3)

### 2.1 The Theorist — *Probing-HIPS*

#### 코어 알고리즘 (5 phase)

```
Phase 0 (5%)  : PROBE
  - 베이스라인 그리디 5 시드 → 어느 stage 가 binding 인지 측정
  - 인스턴스 클래스 추정 (tight-crane / tight-pack / tight-tardiness / loose)
  - Phase 1~3 시간배분 + dual 가중치 결정

Phase 1 (20%) : ASSIGNMENT + TIMING (Aggregated MIP / LP)
  - Gurobi MIP-as-anytime, MIPGap=0.05, TimeLimit=min(0.15·T, 90s)
  - Aggregate spatial cut : Σ area_i ≤ W_j·H_j·u_j·overlap_factor
  - 안 풀리면 LP relaxation 으로 fallback (dual 만 살림)
  - LP/MIP dual → search direction λ 추출

Phase 2 (50%) : PLACEMENT (Lazy NFP + Probe-weighted ordering)
  - NFP 를 *질의 시점*에만 계산 (LRU 2048, polyline only — 메모리 < 1GB)
  - 블록 순서 : EDD × λ_tardiness + (1−λ)·preference (Probe 결과 반영)
  - 크레인 j≥k 위반을 *placement 단계에서 함께* 검증 (Phase 0 prevention)

Phase 3 (20%) : DUAL-GUIDED LNS
  - LP dual reduced cost 큰 블록 = destroy 후보
  - 2-블록·3-블록 simultaneous re-placement (NFP 매니폴드 뚫기)
  - Polyak step rule : step = (UB−LB)/||subgrad||² (hyperparameter 1차원으로 축소)

Phase 4 (5%) : SAFETY NET
  - 미배치/위반 블록 → 빈 베이 windowed force-place (baseline 방식)
  - −1 회피 절대 보장
```

#### 진정한 직교 각도

1. **Phase 0 probe — 알고리즘이 인스턴스를 *측정해서* 자기 자원 배분을 바꾼다.** 대부분의 답안은 "알고리즘 X 를 모든 인스턴스에 동일 적용". 우리는 "어느 stage 가 binding 인지 모른 채 시작하지 않는다." 이건 R−nb 의 비대칭과 직접 연결 — 한 인스턴스 −1 = R/2 손실이라는 사실이 *왜 자가 진단이 필요한지* 정당화한다.

2. **Dual = search direction compass (증명 도구 아님).** 평균은 LP dual 을 bound 증명으로 쓰거나 무시한다. 우리는 dual 을 *비볼록 문제의 informed local search compass* 로 재정의. 학술 문헌에 명시적 정리가 없다.

#### 자인 약점

평균과 같은 부분 : "층으로 분해", "LP/MIP + 메타휴리스틱", "LNS + dual guidance" 는 학술적으로 흔하다. *절반만 다르다*. 두 직교 지점이 살아남으면 R−nb 1~3등 노림. 죽으면 R/2 근처.

---

### 2.2 The Pragmatist — *Hard-Floor + Soft-Ceiling*

#### 코어 운영 골격

```
[설계 단계 — 5월 말~6월 초]
  Layer 0 instance profiler (Contrarian 통찰 흡수)
  K=4 알고리즘 매니폴드 정의 :
    - LNS-seed1 (베이스라인 진화)
    - LNS-seed2 (다른 시드)
    - Greedy-Repair (Phase 2 강화)
    - Topology-MIP (Theorist 또는 Contrarian 의 LP-MIP 흡수)

[제출 사이클당 (1 인스턴스 30분 기준)]
  S0 feasibility 게이트 (절대 양보 X. force_place safety net 마지막 5%)
  S1 mode 이상 게이트 (목적값 분포의 mode 이상이면 채택)
  S2 push 모드 — feasibility 잃지 않으면 무조건 채택 (←R3 진화)
  K=4 병렬, MIP/LNS race + objective-vote (8분 시점에 비교)
  직전 제출 대비 −1 인스턴스 수 +1 비트만 체크 → 증가 시 last_known_good 복귀

[84회 제출 예산]
  학습 X. 회귀 차단만. (R3 진화 : 60비트 신호로 거대 알고리즘 공간 학습 불가능 인정)
  인스턴스 N=15 점수 분포로 우리 위치 (mode/꼬리) 1비트 추정
```

#### Round 3 의 결정적 정정 — 인스턴스 점수 산술

Round 2 에서 "우승 5% × 7천만 vs 안정 60% × 1.5천만" 으로 *총상금 EV* 계산했던 것이 *인스턴스별 R−nb 의사결정* 과는 다른 수학이라는 점 인정. 다시 계산 (R=30 가정) :

| 시나리오 | 인스턴스 점수 |
|---|---|
| 안정 솔루션 (중위, 가운데 클러스터 15팀 안) | 18 |
| 공격 솔루션 (분산 큼, 50%/50% 상위3↔−1) | 13.5 |
| 공격 솔루션 (분산 작음, 70% 상위5 / 30% 중위 / 0% −1) | **23.6** |

**결론** : −1 만 회피하면 공격이 *항상 우월*. 단 *infeasibility 확률이 0에 가까울 때만*. Z1=0 lex 같이 UNSAT 80% 짜리는 점수공식이 *처벌*. 따라서 S2 의 의미는 "개선 없으면 S1 반환" 이 아니라 *"S2 도전이 feasibility 를 잃지 않으면 무조건 S2 채택"*.

#### 진정한 직교 각도

1. **점수 산술을 인스턴스 단위로 재정의**. 평균은 *총상금 EV* 로 말한다. 우리는 R−nb 의 *불연속 클러스터 경계* 를 받아들였고, S2 가 risk-seeking 보상에 *맞춤* 응답.

2. **Fallback → race + objective-vote**. 평균은 "Gurobi 우선, 실패 시 LNS" 순차 fallback. 우리는 *동시 실행 후 objective 비교* 로 "MIP optimal 이면 답" prior 를 깼다.

3. **K=4 매니폴드 직교성 명시**. 평균은 "seed 다양화 + ensemble" 로 끝낸다. 우리는 K의 각 슬롯이 *어느 매니폴드를 대표하나* 명시 (LNS / Greedy / LP-dual / Topology).

4. **12h 학습신호의 정보량 1비트화**. 평균은 "제출로 학습" 막연. 우리는 "학습 X, 회귀 차단 1비트만" 정확히 잘랐다.

#### 자인 약점

R2 산술 오류를 R3 에서 정정한 것 자체가 *과정 신뢰도* 측면에서 약점. K=4 가 4코어/16GB 환경에서 *진짜로* 병렬 가능한지 검증 필요.

---

### 2.3 The Contrarian — *Asymmetric-Game*

#### 코어 직교 골격 (Round 3 축소판)

```
[Round 1: 분류기 — 30초]
  ρ_j 계산, EDD R-violation 추정, 큰 블록 카운트
  → INSTANCE_CLASS ∈ {TIGHT (ρ>0.85), MEDIUM (0.5<ρ≤0.85), LOOSE (ρ≤0.5)}

[Round 2: 페르소나 시간분할 — 5개 → 3개 축소]
  EDD-Greedy++           (모든 클래스, 0-3분, 안전망)
  Topology-MIP Stage-A   (LOOSE 만, 3-15분, abort 가능, Stage-B 좌표는 fall-back)
  Anti-EDD slack-aware   (MEDIUM/TIGHT, 15-25분, 작업부하 우선 정렬)

  ※ LDD 와 Reverse-time 은 Theorist 의 "상관된 minima theorem" 공격으로 드롭

[Round 3: 회피판단 + 제출]
  best incumbent feasibility 5단계 재검증
  if ANY violation → EDD-Greedy fallback 무조건 채택
  25-30분 EXIT
```

#### 의도적 포기 (Contrarian 의 *유일한 무기*)

- **TIGHT 인스턴스 (ρ>0.85) 에서 의도적으로 5분만 쓰고 EDD-Greedy fallback 제출**
- 절약된 시간은 *LOOSE 인스턴스 1등 추구* 에 재배분
- *총점 최대화* 가 아니라 *우측 비대칭 보상 최적화*

#### 진정한 직교 각도

1. **R−nb 비대칭 우측 보상의 *명시적 게임이론적* 최적화**. 평균은 "총점 최대화" 라는 대칭 목적함수를 가정한다. R−nb 는 비대칭이고, *어느 인스턴스에서 nb=0 노리고 어느 인스턴스에서 포기할지* 명시 결정이 알고리즘 핵심 분기로 올라간다.

2. **"의도적 포기" 결정의 알고리즘화**. ρ_j > 0.85 인스턴스에서 *시간을 안 쓴다* 는 선택. 평균은 "모든 인스턴스에 최선" 이라는 도덕적 강박. 우리는 *명시적으로 일부를 버린다*.

#### 84회 제출 예산 사용 (R3 진화)

- **로컬 검증만** : example_B2_b10 + 직접 생성 ρ=0.4/0.6/0.85 synthetic 3개 = 총 6개 × 3 페르소나 = **18 로컬 실행** (제출 예산 0)
- **A/B 제출 단 4회** : 3 페르소나 unified vs EDD-baseline-only, 본선 1주차 batching
- **나머지 80회** : 파라미터 튜닝 (w1/w2/w3 가중조정, 게이팅 임계값)

#### 자인 약점

페르소나별 grand validation 포기 → *로컬 분포와 평가서버 분포 다르면* 모험. 그러나 "분포 다른 게 두려워서 검증 자체를 못 하면 R−nb 비대칭은 영원히 못 활용한다" 가 입장.

---

## 3. 합의된 결정사항 (점수 0순위)

라운드 3 종료 시점에서 *세 명 모두 동의* 한 결정. 이건 무조건 한다.

### 3.1 −1 회피 절대 우선

- 마지막 5% 시간에 *반드시 feasible 한 해를 반환* 하는 safety net (baseline 의 `_force_place` 강화판).
- 모든 솔루션 후보는 `utils.check_feasibility` 5단계 통과 검증 후에만 제출 후보.
- 새 솔루션이 feasibility 잃으면 *즉시 직전 best feasible 로 롤백*.
- 본선 D-1 에 새 빌드가 깨졌을 때 1초 안에 복귀 가능한 `last_known_good.zip` 보존.

### 3.2 인스턴스 프로파일링 (5초 이내)

다음 통계를 알고리즘 시작 5초 안에 계산하고, *이걸로 자원 배분이 바뀐다* :

- **`ρ_j` capacity tightness** (베이별 시공간 빡빡함) — 각 베이 `j` 에 대해 `Σ_i (A_i · P_i) / (W_j · H_j · T_horizon)`
- **블록당 preference concentration `H_i = S_max − S_2nd`** — 강한 선호 = forced bay 후보
- **DAG width estimate** — 시간축 sampling 으로 동시 활성 블록 수 분포
- **w1/w2/w3 비율** — Z1/Z2/Z3 중 어느 게 dominant 인가 (인스턴스 weights 에서 명시적으로 주어짐)
- **블록 크기 분포** (큰 블록 ≥3 개인가) + polygon 정점 분포

이 결과로 4가지 분기 :
- TIGHT (`ρ_j` 최대값 > 0.85) — Contrarian 식 의도적 포기 검토 / Theorist 의 Phase 0 가 시간 적게 배분
- LOOSE (`ρ_j` 최대값 < 0.5) — Topology-MIP / LP-MIP 시도 적극
- TARDINESS-DOMINANT (`w1 · estimated_Z1` >> w2,w3 부분) — EDD 강화
- PREFERENCE-DOMINANT (`H_i > 50` 블록 다수) — 강한 선호 블록 *변수 고정*

### 3.3 K개 매니폴드 후보 (3~4개), 매니폴드 직교성 명시

- *seed 다양화 ≠ 알고리즘 다양성*. seed 만 흔드는 best-of-K 는 redundancy.
- 각 후보는 *서로 다른 매니폴드* 위에 있어야 한다. 합의된 라인업 (3개) :
  1. **EDD-Greedy++** — 베이스라인 진화 (Phase 2 보수 강화). 안전망 역할.
  2. **MIP/LP 기반** — Theorist 의 Layer 1 (Aggregate LP) 또는 Contrarian 의 Topology-MIP Stage-A. 둘 중 어느 것이 LOOSE 인스턴스에서 더 좋은지는 §4.1 실험으로 결판.
  3. **워크로드 균형 우선 (Anti-EDD slack-aware)** — Z2 dominant 인스턴스 대비.

- *최종 솔루션은 check_feasibility 통과한 후보 중 objective 최솟값*. K 끼리 race + 8분 시점 objective-vote.

### 3.4 NFP candidate 는 lazy + LRU (전계산 금지)

- 사전계산 시 메모리 폭발 (12,000 polygon × 200 정점 = 3~5GB) 위험 → 16GB 한도 OOM.
- AABB 겹치는 쌍에 대해서만 *질의 시점에* Minkowski sum 계산. LRU `maxsize=2048`.
- NFP 자체가 아니라 *경계 polyline만* 저장 (정점 ≤ 30). 평균 메모리 < 1GB.

### 3.5 솔버 활용 — race + objective-vote

- Gurobi → Xpress → CP-SAT *순차 fallback* 거부 (Theorist + Contrarian 공격에 Pragmatist 양보).
- 대신 : Gurobi (warm-start 휴리스틱 incumbent 로) + LNS 를 *동시* 실행, 8~12분 시점에 *objective 비교* 후 좋은 쪽 채택.
- 평가서버에서 Gurobi 라이선스 가용성은 *R1 sanity 제출* 에서 명시적 로그 (`license_status`) 박아 검증.

### 3.6 84회 제출 예산 = 회귀 차단 (학습 X)

- 12h 쿨다운 × 84회 ≈ 60비트 / 제출. 거대 알고리즘 공간 학습 불가능.
- 신호는 *직전 제출 대비 −1 인스턴스 수 증가 여부* 1비트만 사용. 증가 시 즉시 last_known_good 롤백.
- 새 빌드는 *로컬 6개 인스턴스 검증* 통과 후에만 제출.

### 3.7 본선 D-1 방어 (Pragmatist 위험 매트릭스 최소 항목)

- 매 제출 빌드에 `[DIAG]` 한 줄 로그 강제 — `gurobi_ok, cpsat_ok, mem_peak_mb, elapsed, phase_reached`. 자동회신 메일에 찍힘.
- `submissions/<tag>/` 에 zip + git diff 보존.
- `last_known_good.zip` 심볼릭링크.
- 평가서버 env 충돌 대비 — `src/` 안에서 무거운 import (`torch`, `tensorflow`, `keras`) 는 *지연 import + try/except*.

---

## 4. 의도적 분기 (실험으로만 결판)

세 명이 *원리적으로* 합의 못 한 부분. 메인 컨텍스트가 임의로 합의시키지 않고, 실험으로 결판낸다.

### 4.1 분기 — Phase 1 의 정체

**누가 옳은가** :
- **Theorist** : Aggregate LP-MIP (bay assignment + time window only, spatial 무시). LP dual 을 search direction 으로 추출.
- **Contrarian** : Topology-MIP Stage-A (베이 안 부분순서만 결정, 좌표는 fall-back).
- **Pragmatist** : 둘 중 어느 것이 K=4 의 한 자리에 들어갈지는 위 둘에 위임.

**실험 설계** :
- 동일 인스턴스 5개 (`B2_b10` example + 직접 생성 ρ=0.4/0.6/0.85 synthetic 3개 + 큰 인스턴스 1개)
- 같은 timelimit (예: 600초)
- 두 변형 빌드를 *동일 K=4 골격* 안에서 한 자리만 바꿔서 측정
- 측정 지표 : *통과한 인스턴스 수*, *목적값 평균*, *솔버 timeout 횟수*
- **결판 기준** : 5개 인스턴스 중 3개 이상에서 *목적값 더 낮은 쪽 + timeout 없음* 채택

### 4.2 분기 — ρ_j > 0.85 인스턴스 처리

**누가 옳은가** :
- **Theorist** : Phase 0 probe 가 알아내고 Phase 1~3 시간 비중 자동 축소
- **Pragmatist** : S0/S1 게이트로 *안전한 mediocre 점수* 확보
- **Contrarian** : 5분만 쓰고 EDD-Greedy fallback, *절약 시간을 LOOSE 인스턴스 1등 추구에 재배분*

**실험 설계** :
- ρ_j > 0.85 합성 인스턴스 5개 생성 (튜브로 베이 채우는 식으로 ρ 강제)
- 세 전략 각각 빌드 → 같은 timelimit 으로 측정
- 측정 지표 : *총점이 아니라 `nb` 분포*. 어느 전략이 어느 인스턴스에서 `nb=0` (1등) 을 가져오는가
- **결판 기준** : R−nb 모델 하에서 *기댓값 차이*. Contrarian 의 의도적 포기 + 다른 인스턴스 push 가 *진짜로* 기댓값을 올리는지 측정. 단 −1 도 같이 따라오면 패배.

### 4.3 분기 — 페르소나 진화 vs 고정

**누가 옳은가** :
- **Theorist + Pragmatist** : 본선 시작 전 페르소나 고정, 84회는 *파라미터 튜닝만*
- **Contrarian** : 본선 1주차 결과 보고 페르소나 *교체 가능*. 실패 페르소나 드롭 + 새 페르소나 ad-hoc 추가

**실험 설계** :
- 본선 1주차 (W1) 종료 후 인스턴스 점수 분포가 *알려진다* 면, 가설 점검 :
  - W1 점수가 *클러스터 중앙 ± 1 표준편차* 안이면 → 고정 유지 (Theorist+Pragmatist)
  - W1 점수가 *클러스터 아래 꼬리* 면 → 페르소나 1개 교체 권리 행사 (Contrarian)
- 결판 기준 : W1 → W2 점수 변화. 페르소나 교체가 *유의미하게 +점수* 면 Contrarian 옳음.

### 4.4 분기 — LP dual 방향 사용처

**누가 옳은가** :
- **Theorist** : dual 을 *search direction compass* 로 사용 (증명 아님), Phase 3 Polyak step rule
- **Pragmatist** : dual 은 bound 표시 정도만, K=4 race 의 한 슬롯에 LP-MIP 후보로
- **Contrarian** : dual = 자기기만, 사용 안 함 (비볼록 MINLP 에서 strong duality 깨짐)

**실험 설계** :
- 동일 인스턴스, 동일 K=4 골격, 마지막 Phase 3 (20% time) 의 사용처를 다르게 :
  - (a) Theorist : dual-guided 2/3-block simultaneous LNS
  - (b) Pragmatist : 단순 LNS destroy/repair (랜덤 + worst-block)
  - (c) Contrarian : LNS 없이 다른 페르소나 추가 시간 배분
- 결판 기준 : 5 인스턴스 평균 목적값. 통계적 유의성 N=5 라 약하지만 *방향성* 은 보임.

### 4.5 분기 — Lex Z1=0 페르소나 포함 여부

**누가 옳은가** :
- **Contrarian** : ρ_j < 0.5 인스턴스에만 활성화, MUS 로 *책임 블록* 식별
- **Theorist + Pragmatist** : NP-complete 결정문제 + UNSAT 80% → 제외

**실험 설계** :
- ρ_j < 0.5 합성 인스턴스 3개 생성
- Lex Z1=0 페르소나 단독 빌드 vs 미포함 빌드 *로컬에서만* 비교
- 결판 기준 : Lex Z1=0 SAT 가 *시간 안에* 결판나는 비율 > 60% + 결판난 경우 *Z2/Z3 가 의미있게 낮음* 일 때만 포함.

---

## 5. 즉시 실행할 액션 (6월 1주차 안에 완료)

§3 합의사항을 *동작하는 코드* 로 옮기는 작업. 우선순위 순.

### A1. `src/profiler.py` — 인스턴스 프로파일러 (5초 이내)

**내용** : §3.2 의 통계 (`ρ_j`, `H_i`, DAG width estimate, w-비율, 블록 크기 분포) 계산. 출력은 *인스턴스 클래스* (TIGHT/MEDIUM/LOOSE/TARDINESS-DOM/PREFERENCE-DOM 라벨) + 권장 시간 배분.

**검증** : `instances/example/example_B2_b10.json` + 직접 생성 ρ=0.4/0.6/0.85 합성 3개에서 5초 이내 완료.

**관련 합의** : §3.2

### A2. `src/safety_net.py` — Force-place safety net

**내용** : baseline 의 `_force_place` 강화판. 마지막 5% timelimit 에 *반드시* feasible 솔루션 반환. 베이별 빈 윈도우 시퀀스 사전구축.

**검증** : 어떤 baseline-깨짐 인스턴스를 넣어도 −1 안 나오는지 단위 테스트.

**관련 합의** : §3.1

### A3. `src/k_manifolds.py` — K=3~4 후보 골격 + race + objective-vote

**내용** : §3.3 의 K=3 라인업 (EDD-Greedy++ / MIP-or-LP / Anti-EDD slack-aware). 각각 별도 worker, 8~12분 시점에 objective 비교, 좋은 쪽 채택. `check_feasibility` 통과 검증 강제.

**검증** : example 인스턴스에서 K=3 각자 단독 vs race 후 비교. race 가 *최솟값* 을 잡는지 확인.

**관련 합의** : §3.3, §3.5

### A4. `tools/build_submission.py` 보강

**내용** :
- `[DIAG]` 한 줄 로그를 `myalgorithm.py` 시작 시 print 강제
- `--strict` 모드 : 로컬 6개 인스턴스 smoke 통과해야 zip 생성
- 직전 zip 과 체크섬 비교 → 같으면 빌드 거부 (12h 쿨다운 낭비 방지)
- `submissions/last_known_good.zip` 심볼릭링크 갱신

**관련 합의** : §3.6, §3.7

### A5. 합성 인스턴스 생성기 `tools/gen_instance.py`

**내용** : `ρ`, `n_blocks`, `n_bays`, `w_ratio`, 평균 polygon 정점 수 를 받아서 합성 인스턴스 생성. §4 의 실험들에 필요.

**검증** : 6개 인스턴스 생성 (ρ=0.4 × 2, ρ=0.6 × 2, ρ=0.85 × 2) 후 baseline 으로 모두 feasible 인지 확인.

**관련 합의** : §3.2 의 분기 실험 준비

### A6. 분기 실험 첫 라운드 (§4.1, §4.4)

A1~A5 완료 후, **6월 2주차 시작 시점** 에 :
- §4.1 (Phase 1 정체) — Theorist Aggregate LP-MIP vs Contrarian Topology-MIP 비교
- §4.4 (Phase 3 dual 사용처) — Theorist dual-guided LNS vs Pragmatist 단순 LNS

각 실험은 *로컬에서만* 결판. 제출 예산 소비 X.

**관련 분기** : §4.1, §4.4

---

## 6. 토론 평가 — 평균 클로드 답변과 진짜 다른가?

토론 자체의 가치 점검 :

| 차원 | 평균 클로드 답변 | 우리 결론 | 진짜 다른가 |
|---|---|---|---|
| 골격 | "LNS + SA + MIP 하이브리드" | K=3 매니폴드 race + objective-vote | 부분적 — race 는 차별, 매니폴드 라인업은 비슷 |
| 점수공식 활용 | "최선 풀이 + 시간 관리" (대칭 EV) | R−nb *비대칭 인스턴스별 의사결정* + 의도적 포기 알고리즘화 | **진짜 다름** (Contrarian + Pragmatist R3 정정) |
| 시간 배분 | 균등 또는 시간 비례 | Phase 0 probe 가 *인스턴스에 맞춰* 자원 배분 | **진짜 다름** (Theorist) |
| Dual 사용 | LP bound 또는 무시 | Dual = search direction compass (증명 아님) | **진짜 다름** (Theorist, 단 검증 필요) |
| 12h 쿨다운 | "제출로 학습" 막연 | 학습 X, 1비트 회귀 차단만 | **진짜 다름** (Pragmatist R3 정정) |
| Fallback | Gurobi→Xpress→CP-SAT 순차 | 동시 race + objective-vote | **진짜 다름** (Pragmatist R3 진화) |
| 페르소나 다양성 | "seed 다양화 + ensemble" | 매니폴드 직교성 명시 + 일부 의도적 포기 | **진짜 다름** (Contrarian + Pragmatist 합작) |

**진짜 다른 6개 지점** 이 우리 차별화의 본체. 이게 *모두* 본선까지 살아남는다는 보장은 없다 — §4 의 실험으로 살아남는 지점만 추린다.

**평균 클로드 비판이 정통 타격한 부분 (Contrarian R2 → 정직 인정)** : "층으로 분해", "LP/MIP + LNS", "phase 2 보수" 의 *기본 프레임* 은 평균과 같다. 그 안의 *세부 선택* (dual = compass, probe, race, 의도적 포기) 이 다르다.

---

## 7. 추후 참고 — 토론 원본 어떻게 보존하나

이 문서는 *정리본* 이다. 라운드별 원본 (각 에이전트 1.5~2 페이지씩 × 3 라운드 = 약 13~18 페이지) 은 *세션 transcript 안에만* 있다.

원본이 필요하면 :
- `C:\Users\peter\.claude\projects\C--claude-develop-OGC2026\` 안의 가장 최근 `.jsonl` 파일에 모든 Agent 호출 결과가 보존되어 있다.

---

**다음 단계** : §5 의 A1~A6 작업. A1~A4 가 코어 합의사항 코드화, A5~A6 가 분기 실험 준비. 본선 등록 (2026-06-07) 까지 약 10일 — 충분히 가능.
