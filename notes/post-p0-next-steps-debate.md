# Post-P0 다음 개선 토론

작성일: 2026-06-02

## 기준선

Post-P0 비교 결과:

- ours vs baseline: 16승 2무 1패 1 both-fail
- head-to-head 점수: baseline 11, ours 36
- baseline judge fail: 6
- ours judge fail: 1

주요 문제 인스턴스:

| Instance | 상태 | 핵심 문제 |
| --- | --- | --- |
| prob_14 | ours feasible, but deadline fail | wall 61.85s, obj 853M |
| prob_16 | ours feasible, baseline에 패배 | ours 376M vs baseline 11M |
| prob_20 | ours feasible, huge objective | obj 1.32B, baseline deadline fail |

P0는 성공했다. `base_budget > T` 제거와 300x4 greedy skip 제거로 큰 timeout/폭발 일부를 막았고, prob_19도 정상권으로 회복했다. 남은 문제는 solver 핵심 구조보다 반환 프로토콜과 폭발 절단 정책에 가깝다.

## A. Deadline/Safety 입장

A의 주장은 단순하다.

P1, 즉 `verified checkpoint + hard deadline` 없이는 어떤 P2도 시작하지 말아야 한다.

근거:

- `prob_14`는 feasible solution을 만들었지만 61.85초로 deadline fail이다.
- `prob_16`도 59.57초로 60초에 너무 붙어 있다.
- 현재 ours는 이미 baseline보다 많이 이긴다. 여기서 탐색을 늘리면 개선보다 timeout 리스크가 먼저 커진다.

A의 우선순위:

1. `check_feasibility`를 통과한 complete solution만 incumbent로 저장한다.
2. Phase-1 완료, repair pass 후, forced completion 후마다 검증 checkpoint를 남긴다.
3. objective가 개선될 때만 incumbent를 교체한다.
4. `0.94T~0.96T`부터 새 repair pass나 큰 scan을 금지한다.
5. `0.98T` 또는 `T-1s`에서 즉시 incumbent를 반환한다.
6. incumbent가 없을 때만 forced completion을 최후 fallback으로 쓴다.

A는 새 알고리즘 도입에 반대한다. 지금 필요한 것은 더 좋은 해가 아니라 절대 빈손으로 끝나지 않는 반환 체계다.

## B. Objective/Explosion 입장

B는 P1에 동의하지만, P1이 단순 deadline guard로 끝나면 부족하다고 본다.

핵심 주장은 `verified checkpoint`가 있어도 "검증된 쓰레기 해"를 반환할 수 있다는 것이다. `prob_16`의 376M, `prob_20`의 1.32B는 feasible이지만 사실상 대패다.

B의 우선순위:

1. `best_feasible_solution`을 항상 보존한다.
2. 후보가 feasible이어도 objective가 기존 best 대비 폭발하면 폐기한다.
3. baseline 또는 baseline-like greedy를 fallback candidate로 보존한다.
4. `prob_14`, `prob_16`, `prob_20`류는 별도 위험 플래그로 분기한다.

B가 제안한 운영 구조:

```text
K candidates:
  A. current ours
  B. conservative baseline-like
  C. due-date-first / tardiness-min
  D. workload-ignore emergency
  E. preference-ignore emergency
  F. small-instance heavier repair

return best verified feasible objective
```

단, B도 대형 MIP, 전면 LNS, SA/GA류 대개편에는 반대한다. 새 알고리즘은 메인 교체가 아니라 후보 생성기여야 한다.

## C. Contrarian 입장

C는 A와 B 모두를 제한적으로만 인정한다.

- A의 안전론만 따르면 점수 천장이 낮아진다.
- B의 objective 개선론이 과하면 `prob_14` 같은 timeout 하나로 전체 기대값을 깎는다.

C의 결론은 `Risk-bounded portfolio policy`다.

즉, 새 packing 엔진을 넣는 것이 아니라 현재 solver 위에 운영 레이어를 올린다.

정책:

- 기본 solver는 현재 ours 유지
- 인스턴스별 위험 플래그 분류
- deadline 위험이면 개선 탐색을 빨리 끊고 checkpoint 반환
- baseline에 지는 유형만 제한적 objective 개선 루틴 허용
- objective가 크더라도 feasible 확보가 어려운 인스턴스에서는 안정성 우선
- 반복 실행에서는 평균이 아니라 최악값과 fail 수를 본다

## 합의 결론

다음 작업은 새 대형 알고리즘 도입이 아니다.

1순위는 P1:

**verified incumbent + hard deadline + objective guard**

구체적으로:

1. `greedyalgorithm()` 내부에 `best_verified` 구조체를 둔다.
2. complete solution이 만들어질 때마다 `check_feasibility`로 검증한다.
3. 검증 통과 후보만 objective를 계산해서 incumbent와 비교한다.
4. objective가 더 좋을 때만 incumbent를 교체한다.
5. soft deadline 이후에는 새 repair/big scan을 시작하지 않는다.
6. hard deadline 진입 시 즉시 `best_verified`를 반환한다.
7. `best_verified`가 없을 때만 현재 forced completion을 최후 fallback으로 쓴다.

2순위는 운영 레이어:

**risk-bounded portfolio**

후보:

- current ours
- conservative baseline-like fallback
- tardiness-first emergency mode
- prob_16 전용 제한 repair
- prob_14/prob_20 deadline-safe early return policy

도입 순서:

1. P1 checkpoint/deadline부터 구현
2. prob_14/prob_16/prob_20 10회 반복 검증
3. fail이 0인지 확인
4. 그 다음에 baseline-like fallback 후보 추가
5. 마지막으로 prob_16 objective 개선 루틴 실험

## 명시적 비합의

남은 비합의는 두 가지다.

1. objective guard를 P1에 포함할 것인가
   - A: P1은 deadline safety만으로 충분하다.
   - B: P1에 objective circuit breaker까지 포함해야 한다.
   - C: guard는 넣되, fail risk를 키우는 복잡한 후보 경쟁은 P1 이후로 미룬다.

2. best-of-K를 언제 넣을 것인가
   - A: P1 이후에도 조심해야 한다.
   - B: baseline-like fallback은 즉시 필요하다.
   - C: 현재 solver를 건드리지 않는 운영 레이어라면 P1 이후 제한적으로 허용한다.

## 실험 기준

평균 objective는 1순위 지표가 아니다.

실험 판정 순서:

1. judge fail 수가 0인가
2. 반복 실행 최악 wall time이 deadline 아래인가
3. baseline 대비 losses/both_fail이 줄었는가
4. prob_14/prob_16/prob_20의 max objective가 줄었는가
5. 전체 head-to-head 점수가 유지 또는 개선됐는가

추천 ablation:

```text
P0 current
P0 + verified checkpoint
P0 + verified checkpoint + hard deadline
P0 + verified checkpoint + hard deadline + objective guard
P0 + risk-bounded portfolio
```

## 최종 결정

바로 구현할 다음 개선은 다음 하나로 고정한다.

```text
P1 = verified checkpoint + hard deadline + minimal objective guard
```

새 알고리즘은 지금 전면 도입하지 않는다. 대신 P1이 안정화된 뒤, baseline-like fallback과 prob_16 전용 제한 repair를 candidate generator로 붙인다.
