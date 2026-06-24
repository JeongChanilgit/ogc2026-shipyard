# Submissions

본 폴더는 OGC 2026 평가 서버에 보낸 제출 아카이브 및 메타데이터를 보관한다.

## 파일 명명 규칙

```
<tag>-<YYYYMMDD-HHMMSS>.zip
<tag>-<YYYYMMDD-HHMMSS>.meta.json
```

예) `v02-lns-20260620-143012.zip`, `v02-lns-20260620-143012.meta.json`

`tools/build_submission.py --tag v02-lns` 가 자동 생성.

## 제출 로그

| 날짜 (KST) | 태그 | 핵심 변경 | 결과 (LB 점수 / 티어) | 비고 |
|----------|------|----------|---------------------|------|
| TBD      |      |          |                     |      |

> 제출 후 운영위 자동회신을 받으면 위 표에 결과 추가. **각 제출에 대한 LB 응답 시각**을 기록해 두면 12시간 쿨다운 계산이 쉬워진다.

## 제출 시 체크리스트

- [ ] `python -m pytest tests/test_smoke.py` 통과
- [ ] `python tools/run_local.py instances/example/example_B2_b10.json --timelimit 60` 통과
- [ ] (training 인스턴스 공개 시) 모든 training 인스턴스에서 feasibility=True 확인
- [ ] `python tools/build_submission.py --tag <태그> --note "<무엇이 달라졌는지>"` 실행
- [ ] 생성된 zip 크기 ≤ 15MB 재확인
- [ ] 직전 *수락된* 제출 시각으로부터 **12시간** 지났는지 확인
- [ ] 등록된 이메일에서 `submission@optichallenge.com` 으로 발송
- [ ] 자동회신 수령 후 본 표에 결과 기록
