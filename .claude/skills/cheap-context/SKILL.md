---
name: cheap-context
description: OGC2026 작업공간에서 토큰(컨텍스트)을 아끼는 작업 규칙. 거대한 인스턴스 JSON(1~3MB)·HTML 리포트(0.3~1.7MB)·PDF(2.4MB)를 Read 로 통째로 빨아들이지 않고 요약만 뽑는 패턴, 무거운 탐색/실행을 서브에이전트·백그라운드로 분리하는 패턴을 강제한다. 사용자가 "/cheap-context", "토큰 아껴줘", "컨텍스트 아끼면서", "싸게 봐줘", "큰 파일 요약만", 또는 인스턴스/결과 파일을 들여다보려 할 때 이 규칙을 먼저 적용하라. 새 세션·/compact 직후 토큰 절약 모드로 진입할 때도 사용.
---

# cheap-context — OGC2026 토큰 절약 작업 규칙

이 스킬이 호출되면(또는 토큰 절약 모드로 일할 때) 아래 규칙을 **이번 세션 내내** 따른다.
규칙의 근거는 이 워크스페이스에서 실측한 파일 크기다 — 추상론이 아니라 이 디렉터리에 맞춘 결정이다.

## 0. 한 줄 원칙
> **큰 파일은 Read 하지 말고, 옆에 있는 작은 요약을 읽거나 `tools/peek.py` 로 수치만 뽑는다.
> 무거운 탐색·웹페치·다파일 정독은 서브에이전트에 위임해 메인 컨텍스트를 보호한다.**

## 1. 절대 Read 하지 말 것 (실측 크기)
| 패턴 | 크기 | 대신 할 일 |
|---|---|---|
| `instances/**/*.json` | 1~3 MB (prob_14 = 3.2MB ≈ **80만 토큰**) | `python tools/peek.py <파일>` |
| `results/**/*.html`, `figures/**/*.html` | 0.3~1.7 MB | 같은 폴더의 `report.md` (≈2KB) 를 Read |
| `docs/*.pdf` | 2.4 MB | `Read` 의 `pages=` 인자로 필요한 쪽만 (한 번에 ≤20쪽) |
| `results/**/sol_*.json` | 수십 KB~ | `python tools/peek.py <파일>` (operations 카운트만) |
| `*.jsonl`, `*.log` 큰 것 | 가변 | `Grep` 으로 패턴만, 또는 `Bash` 로 `Select-Object -Last N` |

**Read 전 습관**: 경로가 위 패턴에 걸리거나 크기가 의심되면 먼저
`Bash`로 `ls -la <파일>` 또는 `python tools/peek.py <파일>` 을 돌려 크기를 확인하고 결정한다.

## 2. `tools/peek.py` — 만능 싼 인스펙터
```bash
python tools/peek.py instances/train/prob_5.json   # bays/blocks/weights + 블록 통계
python tools/peek.py results/<dir>/sol_prob_10.json # operations 카운트·시간범위
python tools/peek.py results/<dir>/                 # 폴더 내 작은 요약파일 목록 (READ-OK 표시)
python tools/peek.py any.json --keys                # 임의 JSON top-level 스키마
python tools/peek.py any.json --path bays.0         # 특정 경로만
```
인스턴스 1MB 파일을 ~15줄 요약으로 줄인다 (≈수십만 토큰 → ~수백 토큰).

## 3. 결과(results/) 보는 순서
1. `python tools/peek.py results/<dir>/` 로 어떤 파일이 작은지 본다.
2. `report.md`, `summary.json`, `score_*.json` (모두 < 1KB) 만 Read.
3. `report.html` 은 **절대** Read 안 함 — 시각 확인이 필요하면 사용자에게 브라우저로 열라고 안내.
4. 여러 score JSON 을 한꺼번에 비교할 땐 Read 대신:
   `python -c "import json,glob; [print(f, json.load(open(f))) for f in glob.glob('results/<dir>/score_*our.json')]"`

## 4. 솔버 실행 — 출력으로 컨텍스트 채우지 말기
- 긴 실행은 `Bash` `run_in_background: true` 로 돌리고, 끝나면 **요약 파일만** 읽는다.
- stdout 을 그대로 받지 말고 파일로 떨군 뒤 `peek`/`Grep`:
  ```bash
  python tools/run_local.py instances/example/example_B2_b10.json --timelimit 60 > results/_run.log 2>&1
  ```
  그 후 `Grep` 으로 `score|infeasible|tardiness` 같은 키워드만 추출.
- 이미 `tools/analyze_run.py`, `tools/feasibility_check.py` 등 요약기가 있으니 **원시 출력 대신 그걸 호출**.

## 5. 탐색·정독은 서브에이전트로 위임 (메인 컨텍스트 보호)
- **넓은 검색** ("이 로직 어디 있어", 네이밍 컨벤션 훑기) → `Explore` 에이전트. 결론만 받는다.
- **여러 파일 정독 후 종합** (예: src 전체에서 크레인 제약 처리 흐름 정리) → `general-purpose` 에이전트에 위임.
- **웹 리서치** → `market-researcher` / `general-purpose` 서브에이전트 (웹페치 토큰을 메인이 직접 안 먹음, ~90% 절감).
- 위임 시 프롬프트에 "파일 덤프 말고 결론·핵심 수치·file:line 만 반환" 을 명시.

## 6. 일반 습관
- **재읽기 금지**: 방금 Edit/Write 한 파일을 검증용으로 다시 Read 하지 않는다 (하니스가 상태 추적함).
- **스코프 Read**: 큰 소스(`src/myalgorithm.py` 등)는 `offset`/`limit` 또는 `Grep` 으로 필요한 함수만.
- **Grep > 통째 Read**: 심볼·문자열 찾을 땐 `Grep` (`output_mode:"content"`, 좁은 `glob`).
- **권한 프롬프트 절감**: 반복되는 읽기전용 Bash 가 매번 승인 요청이면 `/fewer-permission-prompts` 로 allowlist 등록.

## 7. 점검(선택)
이 스킬을 처음 호출하면 한 번 워크스페이스 상태를 보여줘도 좋다:
```bash
find instances results figures docs -type f \( -name "*.json" -o -name "*.html" -o -name "*.pdf" \) 2>/dev/null \
  | xargs ls -la 2>/dev/null | sort -k5 -rn | head -10 | awk '{print int($5/1024)"KB\t"$9}'
```
가장 큰 "Read 금지" 파일들을 사용자에게 상기시킨다.
