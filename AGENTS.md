# Codex 컨텍스트 가이드 — OGC 2026 작업공간

> **이 파일을 가장 먼저 읽어라.** 새 세션이거나 `/compact` 직후라면 이 문서가 작업 컨텍스트를 빠르게 복원시킨다.

## 1. 프로젝트 정체

- **무엇** : **OGC 2026** (Optimization Grand Challenge 2026, LG CNS × 대한산업공학회 주최) 참가 작업공간
- **문제** : **The Grand Shipyard Puzzle: Pack the Block, Beat the Clock** — 조선소 블록의 *베이 배정·위치·방향·진입/퇴출 시각* 을 동시에 결정해 *지연 + 작업부하 불균형 + 선호도 페널티*의 가중합을 최소화
- **상금** : 총 KRW 2억 (약 $130K+), 1등 7천만 원
- **참가 단위** : 1~3명 팀, 등록 2026-05-25 ~ 06-07 KST
- **사용자** : 이 워크스페이스 소유자가 OGC 2026 참가자(예정/참가 중)

## 2. 필독 문서 (우선순위 순)

1. **`docs/problem-analysis.md`** — 600줄 분량 문제 상세 분석. 풀이 시작 전에 반드시 정독.
2. **`docs/problem-statement-v1.0.pdf`** — 운영위 공식 문제 정의서 (v1.0, 2026-05-16, 14p)
3. **`OGC2026-대회개요.md`** — 대회 일정·상금·정책
4. **`README.md`** — 빠른 시작 + 폴더 구조
5. **`baseline/ogc2026/baseline/baseline_greedy.py`** — 공식 베이스라인 (EDD + Best-Fit + Phase 2 repair)
6. **`baseline/ogc2026/baseline/utils.py`** — `check_feasibility` 5단계 검사기, 기하 유틸 (**수정 금지**)

## 3. 작업 규칙 (절대 어기지 말 것)

### 3.1 코드 수정 영역
- ✅ 작업 파일 : `src/myalgorithm.py` (제출 엔트리)
- ✅ 자유롭게 추가 : `src/` 안의 다른 헬퍼 모듈
- ❌ **`src/utils.py` 수정 금지** — 평가 서버가 덮어쓰므로 변경해도 무의미하고, 로컬 테스트에서만 다른 결과를 내면 디버그 지옥
- ❌ **`baseline/` 폴더 수정 금지** — 원본 보존용

### 3.2 알고리즘 시그니처
```python
def algorithm(prob_info: dict, timelimit: float) -> dict:
    ...
    return solution   # {"operations": {str_time: [op, ...]}}
```
**이 시그니처는 절대 변경 금지.** 평가 서버가 이 함수를 직접 호출.

### 3.3 제출 제약
- zip 루트에 `myalgorithm.py` (서브폴더 X)
- zip ≤ 15 MB
- 12시간 쿨다운 (수락된 제출 이후)
- 등록된 이메일로 발송 → `submission@optichallenge.com`

### 3.4 평가 서버 제약
- 4 CPU 코어 (400%), 16 GB 메모리
- **인터넷 차단** (firejail) — 외부 API 호출 절대 금지
- **GPU 없음** — ML 알고리즘은 CPU 전용
- 시간 제한 : 인스턴스별 수 분 ~ 30분 (벽시계)

## 4. 점수 모델 (핵심 의사결정 기준)

```
score(team, instance) = -1                    if infeasible / timeout / crash
                       = R - nb                if feasible
                          (R = #teams, nb = #teams strictly better)

total = Σ score over all instances
```

**시사점** :
- **−1 회피가 1순위** — 한 인스턴스 실현불가 = -1, 평균 R/2 손실
- **동점 OK** — `nb` 는 *엄밀히* 더 좋은 팀 수
- 한 문제 압도보다 **모든 문제 안정적 실현가능** 이 유리

## 5. 현재 상태 (2026-05-28 기준)

- ✅ 대회 등록 페이지·문제 PDF·베이스라인 패키지 다운로드 완료
- ✅ 문제 상세 분석 문서 (`docs/problem-analysis.md`) 작성 완료
- ✅ 폴더를 대회 양식으로 정리 완료
- ⏳ **다음 예정 작업** : **3-에이전트 토론** 으로 풀이 전략 도출
  - 세 명의 서로 다른 관점을 가진 에이전트가 토론
  - 목표 : *전형적인 Codex 답변과 다른* 차별화된 접근
  - 토론 결과는 `notes/strategy-debate.md` 에 정리

## 6. 도전과제 핵심 (한 화면 요약)

### 문제 본질
**3가지 NP-hard 문제가 동시 결합** :
1. 2D 이형 폴리곤 패킹 (Irregular Strip Packing)
2. 단일머신 tardiness 최소화 스케줄링
3. 베이 배정 + 선호도 가중

### 제약 그룹
- **할당** : 모든 블록이 정확히 1 베이 (1 ENTRY + 1 EXIT)
- **시간** : `ENTRY ≥ R`, `EXIT - ENTRY ≥ P`
- **공간** : (1) 베이 경계 (2) 동일층 충돌 금지 (3) **크레인 수직접근** — `j ≥ k` 규칙, 진짜 어려움

### 목적함수
```
min  w1·Z1 + w2·Z2 + w3·Z3
    Z1 = Σ tardiness
    Z2 = max workload imbalance (with bay weight u_j)
    Z3 = Σ (S_max - S_chosen) preference deviation
```

### 의사결정 (블록당 동시)
1. 베이 `j`
2. 위치 `(x, y)` 정수
3. 방향 `o`
4. ENTRY 시각
5. EXIT 시각

## 7. 베이스라인 약점 (개선 여지)

`docs/problem-analysis.md` §6.4 에서 도출 :
1. 그리디 only — 메타휴리스틱 미사용
2. **MIP 솔버 (Gurobi/Xpress) 무료인데 미활용**
3. 시간 슬라이스 후보 단순 (기존 exit_time 만)
4. 방향 선택 베이별 학습 없음
5. Phase 2 가 사후 보수 — 크레인 제약 통합 미완
6. 선호도 가중치 컨텍스트 무시

## 8. 자주 쓰는 명령

```bash
# 환경 활성화
conda activate ogc2026

# 로컬 실행 (예시 인스턴스, 60초)
python tools/run_local.py instances/example/example_B2_b10.json --timelimit 60

# 스모크 테스트
python -m pytest tests/test_smoke.py -v

# 제출 zip 빌드 (태그 자동)
python tools/build_submission.py --tag v01-baseline

# GUI 테스터 (PyQt6)
cd baseline/ogc2026/alg_tester
python alg_tester_app.py
```

## 9. 메모리 (사용자 환경 정보)

- OS : Windows 11 (PowerShell + Bash 모두 사용 가능)
- Working dir : `C:\Codex-develop\OGC2026`
- Python 시스템판 : 3.13 (PDF 추출 등 잡일용), conda 환경판 : 3.12 (실제 솔버 실행용)

## 10. 토론 셋업 가이드 (다음 단계용)

사용자가 "전략 토론 해줘" 또는 유사 요청 시 :

### 에이전트 3명 페르소나
- **A. The Theorist** — 문제 구조 활용, 다항시간 서브문제, 이론적 한계 분석에 집중. 원리주의자.
- **B. The Pragmatist** — 대회 우승 공식 (인프라, 앙상블, 시간관리, 견고성) 중심. "이론보다 엔지니어링".
- **C. The Contrarian** — 두 입장 모두에 질문 던지는 역할. 직교적 각도, *다른 사람들이 안 보는* 관점 발굴. 점수공식 `R-nb` 의 비대칭성, 인스턴스별 차별화, decomposition 방향 재배치 등.

### 토론 원칙
1. **3 에이전트 모두 다른 perspective** — 동의보다 *반박과 갈등* 우선
2. **클로드 평균 답변 회피** — 너무 흔한 "LNS + SA + MIP 하이브리드" 같은 일반론은 점검 통과 못함
3. **구체성 강제** — 추상 권고 X, *이 문제·이 평가서버·이 점수공식* 에 맞춘 결정
4. **최종 산출물** : `notes/strategy-debate.md` 에 정리. 3개의 입장 + 합의 + 명시적 비합의 모두 보존

### 토론 진행 방식 권장
- 라운드 1 : 각 에이전트 단독 의견 (다른 둘은 모름)
- 라운드 2 : 서로의 의견 보고 *공격*
- 라운드 3 : 수정된 입장 + 합의점/비합의점 도출
- 최종 : 메인 컨텍스트가 통합 정리

토론 시작 명령 (메인 컨텍스트가 실행) :
```
Agent 호출 3개 병렬 → 각자 자신의 관점에서 전략 초안 작성
→ 결과 수집 → 각 에이전트에게 다른 둘 의견 보여주고 반박 요청
→ 최종 라운드 → notes/strategy-debate.md 작성
```

<!-- BEGIN CODEX ECONOMIC AGENT DEFAULTS -->

## Codex Economic Agent Defaults

Apply these defaults to all non-trivial work in this project unless the user explicitly overrides them.

This managed section is the base layer for project instructions. Project-specific rules, commands, architecture notes, and constraints should be added after this section. Do not replace or delete this section when creating `AGENTS.md`, `agents.md`, `agent.md`, or `CLAUDE.md` unless the user explicitly asks.

- Optimize for outcome quality per token, wall-clock time, and cost.
- Start with cheap context inventory: file lists, `rg`, metadata, headings, source snippets, and current app state before reading whole files.
- Read deeply only where the next decision requires it.
- Keep raw context in files; bring compact facts, line references, source links, and decisions into the prompt.
- Prefer retrieval, summaries, durable notes, caches, and token ledgers over repeatedly loading large material.
- Route work before doing it: choose model/effort, context budget, tools, agents, and verification level based on task size, risk, freshness, and artifact type.
- Use cheaper/faster routes for routine search, edits, verification, compression, and source gathering; escalate only for architecture, hard debugging, high-risk judgment, or final synthesis.
- Retrieve before full-load and compress after retrieval. Use local search/snippets/context packing before reading entire folders, logs, or long docs.
- Reuse stable facts and recent equivalent work instead of rediscovering them. Store durable project decisions in `AGENTS.md`, project docs, skill references, or a local ledger when useful.
- At project start, ensure both `AGENTS.md` and `CLAUDE.md` exist. If either is missing, run `python C:/Users/peter/.codex/scripts/ensure_project_instructions.py .`.
- Maintain a project file map document for non-trivial repos. Consult it before broad source reads, and update it when the repo structure or important entrypoints change.
- Maintain named task-unit workflows for repeated or complex work. Each workflow should list its steps and the exact folders/files each step may read; during a step, read only those paths unless the workflow is updated first.
- Project `AGENTS.md`/`CLAUDE.md` files should point to the file map and list the active task units with their workflow locations.
- When a file map path, task unit, or workflow location changes, update both `AGENTS.md` and `CLAUDE.md` in the same turn.
- Retry flaky browser/tool setup once; then switch to static, DOM, command-line, or source-level verification instead of burning usage.
- For broad, research-heavy, or multi-file work, look for independent sidecar tasks that can run in parallel.
- Use subagents when permitted and useful for bounded research, disjoint implementation slices, verification, log compression, or risk review.
- Keep the immediate blocker and final integration local; do not delegate the next critical-path decision.
- Prefer 1-3 subagents by default, with clear role, ownership scope, output format, stop condition, and "do not revert others" warning.
- Verify with focused tests, source checks, screenshots, rendered artifacts, or line-level inspection as appropriate.
- Include material telemetry in handoffs: agents used, context loaded, tests run, cache reuse, and unresolved risk.
- Prefer the installed skill for this workflow: `C:/Users/peter/.codex/skills/cost-efficient-agent-workflow`.

<!-- END CODEX ECONOMIC AGENT DEFAULTS -->

<!-- BEGIN PROJECT FILE MAP AND TASK WORKFLOWS -->

## Project File Map And Task Workflows

- File map: TODO. Prefer `docs/file-map.md`, `Docs/file-map.md`, or the closest existing project docs location.
- Rule: consult the file map before broad source reads, and update it when structure, entrypoints, generated areas, or do-not-touch zones change.
- Task units:
  - TODO: name the task unit and link its workflow.
- Workflow rule: each task-unit workflow must list step-level allowed read paths. During a step, read only those folders/files unless the workflow is updated first.
- Cross-AI sync rule: when file map, task units, or workflow locations change, update both `AGENTS.md` and `CLAUDE.md` in the same turn.

<!-- END PROJECT FILE MAP AND TASK WORKFLOWS -->

## Project Context Boundaries

> **★★★ 2026-06-18 (LATEST — read FIRST): `notes/SESSION-HANDOFF-2026-06-18.md`.** Adopted this
> session (baked into src/ defaults): **gassign-first PURE** (set2 z1 −95.7%) + **C3_MULT=2.0**
> (gassign master z3-bias, `gassign.py:368`) → set2 **271.93M, BEATS competitor 279.82M by 7.89M**,
> set1 −1.96%, feasible 40/40 never−1. Submission zip built+validated: `submissions/
> v-gassign-c3mult2-2026-06-18-*.zip`. PENDING (next session): wire the **windowed relayout polish**
> (`src/relayout.py`, validated post-hoc set2 −2.6M → lead −10.49M, never-worse) into myalgorithm.py
> as a gated final stage + validate under real leftover-wall budget. Track ledger: `notes/research/
> assignment-z3-ledger.md`. The 2026-06-15 banner below is now HISTORY (hybrid best-of superseded by
> gassign-first PURE).

> **★★★ RESTORE 2026-06-15 PM (supersedes the 2026-06-14 RESET).** The fresh-start rebuild
> (box-decomp/feasspill) REGRESSED set1 to ~5M; the pre-reset OLD solver already hit set1 **1,385,779**
> (z1=0 on 19/20, 10/20 wins). **The old solver is RESTORED to `src/`** (`archive/old-solver-src-2026-06-14/*.py`,
> utils.py kept official). Fresh-start preserved at `notes/research/myalgorithm-freshstart-2026-06-15.py`.
> Root cause of the regression: box-decomp searched position+time JOINTLY (explodes); the old solver
> DECOUPLES — greedy crane-aware BL layout (`fastfloor._fixed_time_decode`) fixes positions, then a
> per-bay CP-SAT **timing oracle** (`_cpsat_bay_timing_verified`) on the FIXED layout = a clean 1-D
> disjunctive tardiness problem solved to optimum. **`src/` now = the old multi-module solver**
> (myalgorithm.py + fastfloor/baseline_greedy/uconstruct/baypack_cp/packer/rebuild/regime/z3race/…).

- **단일 진실 소스 (가장 먼저 읽어라)**: `notes/research/INSIGHTS.md` §0 PIVOT banner (restore rationale,
  the decoupling technique, set1 1.39M state, gap-to-<1M analysis). Then the old-solver handoff
  `notes/SESSION-HANDOFF-2026-06-14-rebuild.md` + `notes/devlog/integration-map.md`/REFLECTIONS.md.
  (`notes/FRESH-START-INSIGHTS-2026-06-14.md` is now HISTORY — it described the discarded fresh-start.)
- **GOAL (user, Stop-hook): set1 총 obj < 1,000,000.** Old solver = 1.39M (z1=0 on 19/20; losses
  z3-dominated, 2-4× comp). <1M needs BEATING the near-optimal competitor's packing DENSITY (the
  polygon-nester lever, FALSIFIED) — practical ceiling ~1.3-1.4M. Increment: HYBRID best-of(old,
  fresh-start) ≈ 1.315M (fresh-start beats old on prob_3/4/18).
- **활성 솔버 (`src/myalgorithm.py` = HYBRID, 2026-06-15)**: `algorithm()` = best-of(`_legacy_algorithm`
  [복원된 옛 솔버] , `boxsolver.algorithm` [= box-decomp, `src/boxsolver.py`]). 게이트 `OGC_HYBRID`(default
  ON; =0 ⇒ 순수 legacy). **full set1 = 1,312,961**(`baselines/hybrid_set1.json`, old 1.39M에서 −73K;
  box가 prob_3/4/18 win, legacy가 congested 나머지 win). legacy = T≥60 SUBMIT_V2(gate200_v2) z1=0 on
  19/20. 예산: legacy 가 T−reserve(reserve=min(80,0.3T) when T≥150), legacy 는 ~140-300s에 plateau
  ⇒ server-TL 에선 regression 0(local prob_14만 −2918). ⚠ **set2 취약**(legacy 타임아웃 → −1, 원래 리셋
  이유; hybrid 는 box 후보를 try/except+best-of 로 감싸 −1 추가위험 없음) — ALL40 제출 전 legacy TL-
  discipline 보강 필수. 4-worker CP-SAT라 `conda run` 크래시 → env python 직접 실행
  (`C:/Users/peter/anaconda3/envs/ogc2025/python.exe`). 백업: fresh-start = `notes/research/freshstart.py`.
- **인스턴스**: `instances/train/` = set1(prob_1..20, 경쟁자 테이블 있음) + **set2(prob_21..40, 2026-06-14
  추가, 더 큼/3~4 layer 다수, 경쟁자 테이블 없음)**. 가중치가 자릿수 단위로 다양(w1 667~29.6K) → 반드시
  weight-adaptive. 하니스 `notes/_capture20_aff.py`는 `--instances ALL20|SET2|ALL40` 지원.
- **반증된 레버(재시도 금지)**: LCA/contact-area 배치·temporal 사전-staggering·finer-raster·exact box
  packer. 근거: `notes/structural-ceiling-2026-06-14.html` + `notes/devlog/REFLECTIONS.md`(2026-06-14 PM).
- 측정/채택 규칙(사용자 지시): 검증은 **full set**(set1 또는 ALL40), 판정 기준은 **개별 z가 아니라 총 obj**.
- 과거 산출물은 역사 참조용: `notes/SESSION-HANDOFF-2026-06-14-rebuild.md`(옛 솔버, §4 FALSIFIED 배너),
  `research/z1-tardiness/`(Z1 문헌 147편), `notes/strategy-research-2026-06-11.html`.
- **수정 금지**: `src/utils.py`(평가서버가 덮어씀)·`baseline/`. `algorithm(prob_info, timelimit)` 시그니처 불변.
