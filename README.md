# OGC 2026 — Solver Workspace

> 본 저장소는 **Optimization Grand Challenge 2026 (LG CNS × KIIE)** 참가용 작업공간이다.
> 문제: **The Grand Shipyard Puzzle — Pack the Block, Beat the Clock** (조선소 블록 공간·시간 통합 스케줄링).

## 폴더 구조

```
OGC2026/
├── README.md                    # ← 지금 여기
├── CLAUDE.md                    # Claude 세션이 컨텍스트 잃었을 때 읽는 입구
├── OGC2026-대회개요.md          # 대회 운영·일정·상금 요약
├── docs/                        # 문제 정의 + 분석
│   ├── problem-statement-v1.0.pdf
│   ├── problem-statement-v1.0.txt   # PDF 추출 텍스트
│   ├── problem-analysis.md          # 문제 상세 분석 (필독)
│   └── extract_pdf.py
├── baseline/                    # 공식 베이스라인 패키지 (원본 보존)
│   └── ogc2026/...
├── src/                         # 작업 중인 솔버 코드 (제출 단위)
│   ├── myalgorithm.py           # 제출 엔트리 — 시그니처 고정
│   ├── baseline_greedy.py       # 베이스라인 그리디 (참고/시드용)
│   └── utils.py                 # 검사기·기하 유틸 (수정 금지)
├── instances/                   # 문제 인스턴스
│   ├── example/                 # 베이스라인 예시
│   │   └── example_B2_b10.json
│   └── training/                # 운영위 배포 예정 (TBA)
├── experiments/                 # 탐색·아이디어 검증
├── tests/                       # 회귀·스모크 테스트
├── tools/                       # 빌드/제출/로컬 실행 스크립트
│   ├── build_submission.py      # 제출 zip 생성
│   ├── run_local.py             # timelimit 강제 로컬 실행
│   └── feasibility_check.py     # check_feasibility 단독 호출
├── submissions/                 # 제출 아카이브 (날짜별 zip + meta)
├── results/                     # 알고리즘 실행 결과 dump
└── notes/                       # 진행 메모, ADR
```

## 빠른 시작

### 1. 환경 셋업 (최초 1회)
```bash
conda env create -f baseline/ogc2026/ogc2026_env.yml
conda activate ogc2026
```
> conda 가 없으면 [Miniforge](https://github.com/conda-forge/miniforge) 권장. 평가 서버와의 호환성을 위해 conda 사용을 강력히 추천.

### 2. 베이스라인 동작 확인
```bash
python tools/run_local.py instances/example/example_B2_b10.json --timelimit 60
```
출력 : feasibility 결과 + objective 값.

### 3. 알고리즘 수정
- 작업 파일 : `src/myalgorithm.py`
- 시그니처 고정 : `def algorithm(prob_info: dict, timelimit: float) -> dict`
- `src/utils.py` 는 **수정 금지** (평가 서버가 덮어씀)

### 4. 제출 zip 생성
```bash
python tools/build_submission.py --tag v01-baseline
```
→ `submissions/v01-baseline-<날짜>.zip` 생성 + 메타데이터 기록.

### 5. 제출
- 수신 : `submission@optichallenge.com`
- 발신 : 등록된 이메일
- 첨부 : 위에서 만든 zip 1개
- 쿨다운 : 직전 *수락된* 제출 이후 12시간

## 주요 일정

| 날짜 (KST) | 이벤트 |
|----------|--------|
| 2026-05-25 00:00 | Registration Opens |
| 2026-06-07 23:59 | Registration Closes |
| 2026-06-15 14:00 | **Preliminary Opens** |
| 2026-07-28 14:00 | Preliminary Closes |
| 2026-08-03 14:00 | Final Opens |
| 2026-08-14 14:00 | Final Closes |
| 2026-09-04 (TBA) | Awards |

상세 : [OGC2026-대회개요.md](OGC2026-대회개요.md)

## 평가 환경 제약 (재확인)

| 항목 | 한도 |
|------|------|
| CPU | 4 코어 (AMD Threadripper PRO 9955WX) |
| RAM | 16 GB |
| OS | Ubuntu 24.04 LTS |
| GPU | **없음** — ML 은 CPU 전용 |
| 인터넷 | **차단** (firejail) |
| 시간 | 인스턴스별 다름 (수 분 ~ 30분, 종료 후 공개) |
| 제출 zip | ≤ 15 MB |
| 쿨다운 | 12시간 |

상용 솔버 무료 사용 가능 : **Gurobi 13.0.2**, **FICO Xpress 9.8.1**, **OR-Tools 9.15**.

## 다음 작업

- [ ] **전략 토론** (3-에이전트 토론으로 차별화된 접근 도출)
- [ ] 베이스라인 약점 6가지 중 우선순위 결정 → 첫 개선안 PoC
- [ ] training 인스턴스 공개 시 (TBD) 다양성 분석 → 인스턴스별 시간 프로파일링
- [ ] 안전 제출 인프라 완성 (timelimit 가드, 메모리 가드, 정수화 가드)

## 참고

- 공식 사이트 : <https://optichallenge.com/>
- 등록 : <https://ogc2026register.web.app/>
- Discord : <https://discord.gg/VHHdrx9sxs>
