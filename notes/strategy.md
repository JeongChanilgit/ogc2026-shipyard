# OGC 2026 전략 — 솔버 없이 이기기 (리서치 + 2-에이전트 토론 종합)

> 작성 2026-05-29. 입력: `notes/strategy-research.html`(4영역 웹/깃허브 리서치) + 2-에이전트 적대적 토론(분해 캠프 vs 단일-ALNS 캠프, 2라운드).
> 기존 `strategy-debate.md`, `strategy-explained.html`, `post-debate-defense.html`는 건드리지 않음 — 이 문서는 **리서치로 새로 검증된 사실 위에서 다시 도출한 전략**.

---

## 0. 결론 먼저 (한 화면)

**합의 아키텍처 = 분해 골격 + 탐색이 박힌 봉합선(backward edge).**

```
Layer 1 (배정)      block→bay 만 결정. Z2(불균형)·Z3(선호)를 closed-form으로 확정.
   │  CP-SAT(무료·오프라인) 또는 휴리스틱. 패킹가능성 cut 포함.
   │  ▲ no-good cut (lazy constraint)         ← 봉합선: 여기에 탐색(ALNS)이 산다
   ▼  │
Layer 2 (베이별 디코더, 4코어 병렬)   각 베이 독립. ATCS 순서 → BLF 배치 →
      suffix-OR 크레인 검사 → event-time grid ENTRY/EXIT. Z1(지연)+feasibility만 최적화.
      └─ "이 베이는 이 블록셋 못 담음 / i가 너무 늦게 나감" 인증서를 Layer 1로 반환
─────────────────────────────────────────────────────────────────────
안전망: feasible incumbent 먼저 + defer-not-fail + 90% 타임가드 + best-feasible 보관
        + try/except + 반환 전 공식 check_feasibility.  ← −1 절대 회피
레짐 라우팅: w1:w2:w3 + 패킹 밀도 + n 읽고 모드 선택.
```

**왜 이게 이기나:** 점수가 `R − nb`(랭크, 동점=만점, infeasible=−1)이므로 **항상 feasible + 2/3 목적항(Z2·Z3)을 거의 공짜로 최적화**하는 것이 강력하다.

> ⚠️ **2026-05-29 스펙 재감사로 정정:** 공식 문제정의서 §4.1 은 운영위가 **Gurobi 13.0.2·Xpress 9.8.1 을 평가서버에 정식 제공**(Gurobi·FICO 후원, 라이선스 동작)한다고 명시한다. conda env 에도 `gurobipy`·`xpress` 가 들어있다. 따라서 *"상용 솔버 팀은 firejail 라이선스 실패로 스스로 −1"* 이라는 기존 가정은 **틀렸다.** 상용 솔버 팀은 정상적으로 feasible·고품질 해를 낸다. → 우리의 솔버-회피는 *"솔버가 안 돈다"* 가 아니라 **(a) 기술보고서 novelty 가점**(스펙이 명시적으로 보상), **(b) 솔버 라이선스 의존성 제거(견고성)**, **(c) 비정형 패킹은 MIP 가 원래 약한 영역** 이라는 *의식적 선택* 으로 정당화한다. 그리고 "항상 feasible" 은 필요조건일 뿐 — 강한 라이벌을 **목적값(랭크)으로 이겨야** 하므로 메타휴리스틱 품질 요구가 더 높아진다.

---

## 1. 토론으로 검증된 구조적 사실 (이 전략의 주춧돌)

분해 캠프 에이전트가 **`utils.py`를 직접 읽어 확인** (단일-ALNS 캠프도 독립 재확인):

| 사실 | 위치 | 함의 |
|---|---|---|
| **Z2(불균형)는 배정에만 의존** — `obj2 = max\|u_j·load_j − u_k·load_k\|`, `load`는 `bay_loads += workload`뿐 | utils.py:1395–1419 | (x,y)·방향·시각 무관 → 배정만 정하면 Z2 확정 |
| **Z3(선호)도 배정에만 의존** — `obj3 = Σ(S_max − S_ij)` | 동상 | 배정만 정하면 Z3 확정 |
| **Z1(지연)만 기하/시각에 결합** — `obj1`은 `exit_time`에 의존 | utils.py:1402 | 패킹·스케줄링이 Z1을 통해서만 목적함수에 들어옴 |
| **feasibility는 베이별 독립** — `check_entry/exit/collisions`가 단일 `bay` 인자, cross-bay 결합 0 | utils.py:461/603/727, 1289–1382 | 베이 = 독립 단일-크레인 셀 → 4코어 자명 병렬 |

> 🔑 즉 **3개 목적항 중 2개(Z2·Z3)는 배정 벡터의 순수 함수**, feasibility는 베이별로 쪼개진다. 단일-ALNS 캠프의 "모든 게 기하로 결합" 주장은 **부분적으로 틀림** — Z1만 기하 결합. 이게 분해를 정당화하는 핵심.

---

## 2. 합의 아키텍처 (레이어별)

### Layer 1 — 배정 / 균형 (Z2·Z3 확정)
- **결정**: `block → bay`만. 목적 `min w2·Z2 + w3·Z3` (둘 다 closed-form).
- **솔버**: **OR-Tools CP-SAT** — pip wheel에 포함, 라이선스 서버 없음 → 무인터넷 box에서 합법·안전. (Gurobi/Xpress 도 서버에 정식 제공되어 *사용은 가능*하나, 위 §0 정정대로 **우리는 novelty·견고성을 위해 의식적으로 안 쓴다.** "솔버가 안 돈다"가 아니라 "안 쓴다"가 정확한 표현.)
- **제약**: 베이별 패킹가능성 제약 — 단, **"면적 ≤ 베이면적"은 필요조건일 뿐 충분조건 아님** (비정형 2.5D + 크레인 `j≥k` 때문에 면적 남아도 못 담을 수 있음). 그래서 정적 면적힌트가 아니라 **Layer 2가 발견해 돌려주는 no-good cut으로 점진 강화** (§3).

### Layer 2 — 베이별 디코더 (Z1 + feasibility), 4코어 병렬
배정이 고정되면 각 베이는 독립 = 2D 비정형 패킹 + 단일머신 tardiness:
1. **ATCS 순서** — release(`ENTRY≥R`) 처리 + 인스턴스별 w1에 맞춘 look-ahead κ. 폴백 MDD/EDD.
2. **Bottom-Left-Fill 배치** — 방향별 사전계산 **이산 NFP/IFP**, 정수 raster, NumPy 비트마스크 AND로 동일층 충돌.
3. **크레인 feasibility = suffix-OR 비트마스크** — `U[L] = (레벨 ≥ L 공존 footprint OR)`. layer `l1` 추출 가능 ⇔ `footprint(l1) AND U[l1] == 0`. ENTRY/EXIT마다 O(layers) 증분 갱신. 이게 `j≥k` 규칙 그 자체, O(blocks²) 아님.
4. **ENTRY/EXIT = event-time grid** `{R_i} ∪ {기존 EXIT}`, "하루 내 EXIT 먼저 → ENTRY" 규칙 활용.

→ Z2·Z3는 Layer 1이 이미 고정했으므로 Layer 2는 **Z1+feasibility만** 최적화 = 훨씬 well-conditioned.

---

## 3. 봉합선(seam) 해법 — 토론의 핵심 균열, 여기에 탐색이 산다

**문제(양 캠프 모두 지목):** Layer 1이 기하에 눈감고 배정하면, Layer 2가 **물리적으로 못 담는 베이**를 받을 수 있다 → 대량 defer/force-place → Z1 폭발 → w1-지배 인스턴스에서 사실상 −1(랭크).

**합의 해법 = Lazy Constraint Generation (no-good cut 루프):**
- Layer 2가 실패하면 **인증서** 발행: "베이 j는 블록셋 B를 동시 수용 불가" 또는 "블록 i가 due≫ 늦게 EXIT".
- **ALNS가 픽셀(x,y)이 아니라 *배정 레벨*에서 작동**:
  - **destroy**: 최악 tardiness 기여 블록 + 못 담은 베이의 overflow 블록을 eject.
  - **repair**: 새 no-good cut(`Σ B not all in j`)을 넣고 Layer 1 **증분 재해결**.
- **왜 싼가:** Z2·Z3가 closed-form이라 Layer 1 재해결은 기하 재계산 없음(밀리초). 비싼 절반(기하)은 cut 발견 시 1회 패킹 시도로만 들어옴 → "수천 번의 기하 repair"(단일-ALNS의 약점)가 아니라 "수천 번의 조합 이동"(쌈).

> **합의 표현:** 분해 = 골격, **배정-레벨 ALNS = 봉합선의 backward edge**, 기하는 전역 탐색 대상이 아니라 *oracle*(제약 생성기). 기하 realization(BLF/raster)은 절대 전역 탐색하지 않는다.

---

## 4. 견고성 / −1 절대 회피 (단일-ALNS 캠프 기여, 분해 캠프도 채택)

1. **feasible incumbent 먼저**: CP-SAT 초기 배정 + greedy BLF + `_force_place`로 수초 내 확보·저장.
2. **defer-not-fail**: 못 넣으면 ENTRY를 미뤄서라도 항상 feasible (Z1 크더라도 `R−nb ≥ 0` > crash의 −1).
3. ALNS는 **검증된 더 나은 해만 swap-in**, best-feasible는 절대 유실 안 함.
4. **타임가드 90%**: `timelimit` 읽어 직렬화 여유 남기고 중단, `time.monotonic()` 매 반복 체크.
5. 전체 **try/except** → 예외 시 저장 incumbent 반환. **반환 전 공식 `check_feasibility`** 통과 확인.
6. **4코어**: 분해 모드 = 베이별 병렬 디코드 / (escape) 모드 = 독립 ALNS 재시작 + best 마이그레이션.

---

## 5. 인스턴스 레짐 라우팅 (`w1:w2:w3` + 패킹밀도 + n 읽고 분기)

| 레짐 | 특징 | 전략 |
|---|---|---|
| **분해가 명확히 우세** | w2/w3 지배 · 느슨한 패킹 · 작은 n | Layer1(거의 최적 Z2/Z3) + Layer2 거의 그대로. cut 루프 빨리 수렴. |
| **토스업** | 중간 n · w1 지배 | 패킹 tightness가 결정 → 하이브리드 cut 루프. |
| **단일-ALNS escape hatch가 우세** | **가장 큰 + 가장 빡빡한 패킹 + w1 지배** | 배정과 기하가 연속 co-evolve해야 함. Layer1 해로 seed한 **공유 monolithic-ALNS path**로 폴스루. |

→ 한 코드베이스, (적어도) 2모드, **공유 kernel(suffix-OR + raster) + 공유 defer-not-fail + 공유 타임가드.**

---

## 6. 명시적 비합의 (보존 — 구현하며 결정할 것)

1. **monolithic ALNS의 위상**: 분해 캠프는 "빡빡+w1+큰 인스턴스 전용 escape hatch"로 한정. 단일-ALNS 캠프는 "배정-레벨 backward edge로 항상 1급 존재". → 실측 후 결정.
2. **Layer 2 스케줄(Z1) 정밀도**: ATCS 휴리스틱으로 충분 vs 베이별 CP-SAT로 단일머신 tardiness 거의 최적. 베이별 블록 수 작으면 CP-SAT 정밀 풀이 가치.
3. **Layer 1을 CP-SAT vs 순수 휴리스틱**: n 크고 cut 많아지면 CP-SAT 재해결 비용 ↑ — 휴리스틱 배정 + 로컬서치가 나을 수도.
4. **남은 공통 두려움**: 가장 크고 빡빡한 인스턴스에서 cut 루프가 30분 내 수렴 못 할 수 있음 = 정확히 escape-hatch가 필요한 지점.

---

## 7. 구현 우선순위 (다음 액션)

1. **공유 feasibility kernel 먼저** (양 캠프 합의 1순위 레버): suffix-OR 크레인 마스크 + 정수 raster 충돌(NumPy), 증분 갱신. 내부 루프 throughput이 전체 한계 → 여기에 첫 노력.
2. **Layer 1 배정 (CP-SAT, Z2·Z3 closed-form) + 즉시 feasible incumbent + defer-not-fail 안전망.** → 이 단계만으로 베이스라인 대비 −1 위험 제거 + Z2/Z3 우위.
3. **Layer 2 디코더** (ATCS + BLF + 크레인 검사) 베이별 병렬.
4. **봉합선 no-good cut 루프** (배정-레벨 ALNS).
5. **레짐 라우팅 + monolithic escape path.**
6. 매 단계 `tools/run_local.py` + 예시 인스턴스로 검증, `check_feasibility` 게이트.

> 작업 파일: `src/myalgorithm.py`(+ `src/` 헬퍼). `src/utils.py`·`baseline/` 수정 금지. 시그니처 `algorithm(prob_info, timelimit) -> dict` 고정.

---

## 8. 토론 원본 입장 (감사 추적용)

- **분해 캠프 (R1→R2):** Z2/Z3 배정-only·베이 독립을 코드로 검증 → 배정을 CP-SAT로 분리, 베이별 결정론 디코더 병렬. 결정론=증명가능=−1 보험. R2에서 봉합선을 no-good cut 루프로 봉합, monolithic을 escape hatch로 수용.
- **단일-ALNS 캠프 (R1→R2):** 전 변수 통합 ALNS + anytime 하니스, 목적함수가 유일한 튜닝. R2에서 "전부 기하 결합" 주장 철회(Z2/Z3는 배정-only 인정), 그러나 배정이 패킹가능성·Z1에 묶여 *exact-first는 위험* → ALNS를 픽셀에서 **배정 레벨**로 재배치, lazy constraint generation으로 수렴.
- **수렴점:** 분해 골격 + 배정-레벨 ALNS backward edge(패킹/tardiness 인증서 구동) + 공유 anytime 안전망.
