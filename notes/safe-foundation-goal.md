# Goal: 안전한 알고리즘 받침대 만들기

작성일: 2026-06-02

## 목표

새 알고리즘을 추가하기 전에, 어떤 후보 알고리즘이 실패해도 기존 feasibility와 deadline 안전성을 망치지 않는 실행 구조를 만든다.

이 문서의 목표는 `MIP`, `LNS`, `tardiness-first repair`, `portfolio` 같은 새 후보를 올리기 전에 필요한 최소 안전 기준을 명확히 고정하는 것이다.

## 현재 판단

현재 P1 계열 변경으로 다음은 어느 정도 달성했다.

- `check_feasibility`를 통과한 후보만 반환하려는 구조
- deadline 근처에서 무리한 repair를 줄이려는 guard
- `greedy` / `simple` repair를 상황별로 쓰는 운영 레이어
- train 20개 기준 judge fail 감소

하지만 아직 받침대가 완성됐다고 보기는 어렵다.

가장 큰 이유:

- `simple_repair_floor` 선택이 아직 `n_blocks`, `n_bays`, `w1` 구간에 의존한다.
- 이는 문제 번호를 직접 보지는 않지만, train set에 맞춘 feature-based patch에 가깝다.
- hidden/general instance에서는 같은 feature가 다른 의미일 수 있다.

따라서 다음 목표는 weight 구간 분기를 제거하고, 실제 실행 중 관측되는 증상 기반 repair selector로 바꾸는 것이다.

## 안전한 받침대의 정의

안전한 받침대란 다음 조건을 만족하는 실행 구조다.

```text
새 후보 알고리즘이 실패해도
기존 best feasible solution, deadline, objective 품질을 망치지 않는 상태
```

구체적으로는 아래 7개 조건을 만족해야 한다.

## 조건 1: 항상 verified incumbent가 있다

반환 가능한 solution은 반드시 complete solution이어야 하며, `check_feasibility`를 통과해야 한다.

요구사항:

- `check_feasibility(prob_info, sol)` 통과 후보만 incumbent로 저장
- checker가 계산한 `objective`, `obj1`, `obj2`, `obj3`를 authoritative score로 사용
- infeasible 후보는 절대 incumbent로 승격하지 않음
- 새 후보가 crash, timeout, infeasible, worse objective여도 기존 incumbent 반환

완료 기준:

- 어떤 후보 생성기가 예외를 던져도 `algorithm()`은 verified incumbent 또는 안전 fallback을 반환한다.
- 최종 반환 직전 후보가 infeasible인 경우에도 이전 verified incumbent가 있으면 그쪽을 반환한다.

## 조건 2: deadline 근처 행동이 단순하다

deadline 근처에서는 새 작업을 시작하지 않고, 저장된 incumbent를 반환한다.

요구사항:

- soft deadline 이후 새 repair pass 금지
- soft deadline 이후 큰 geometry scan / LNS iteration / full decode 금지
- hard deadline 진입 시 즉시 incumbent 반환
- "마지막으로 한 번만 더" 형태의 예외 경로 금지

권장 기준:

```text
soft deadline: 0.94T ~ 0.96T
hard deadline: min(0.98T, T - safety_margin)
safety_margin: n_blocks 규모에 따라 0.5s ~ 3s
```

완료 기준:

- 반복 실행 worst wall time이 `timelimit`보다 최소 3초 이상 낮다.
- 60초 로컬 기준 위험 인스턴스의 max wall이 57초 이하를 목표로 한다.

## 조건 3: 모든 후보는 gate를 통과해야 한다

quick objective는 ranking에만 쓰고, 반환 여부는 checker gate로 결정한다.

요구사항:

- `_quick_objective`만으로 반환 금지
- candidate는 `check_feasibility` 통과 후에만 best와 비교
- feasible이어도 objective가 incumbent보다 나쁘면 폐기
- objective가 비정상적으로 폭발하면 circuit breaker로 후보 검증 우선순위를 낮추거나 폐기

완료 기준:

- candidate list에 infeasible 후보가 있어도 최종 반환이 오염되지 않는다.
- final return path가 단일 gate를 통과한다.

## 조건 4: repair 선택은 증상 기반이어야 한다

현재의 `n_blocks/n_bays/w1` 구간 분기는 제거하거나 보조 신호로만 사용한다.

대신 실행 중 관측되는 증상을 사용한다.

사용 가능한 증상:

- Phase-1 elapsed ratio
- Phase-1 feasibility stage
- Phase-1 violation count
- Stage-2/Stage-3/Stage-4/Stage-5 violation 비율
- repair pass별 violation 감소율
- repeated offender count
- forced block count
- `obj1` 또는 estimated tardiness 증가량
- max exit time / due date tail ratio
- 현재 solution의 Z1 폭발 여부

repair selector 방향:

```text
if Phase-1 already feasible:
    keep greedy result
elif violations are many but mostly crane boundary and elapsed is high:
    prefer simple repair
elif Z1 / tardy tail is exploding:
    use tardiness-first emergency repair
else:
    use greedy repair with checkpoint guard
```

완료 기준:

- train instance 번호나 weight 구간을 겨냥한 분기가 없다.
- 같은 selector가 `instances/gen`, `instances/stress`, `instances/tard`에서도 fail 증가 없이 동작한다.

## 조건 5: 반복 실행 worst-case가 안정적이다

평균 objective가 아니라 최악 실행을 기준으로 판단한다.

필수 반복 대상:

- `prob_13`
- `prob_14`
- `prob_15`
- `prob_16`
- `prob_17`
- `prob_18`
- `prob_19`
- `prob_20`

측정 기준:

- 각 5~10회 반복
- judge fail 수
- max wall time
- max objective
- objective 폭발봉 출현 여부
- 기존 P0/P1 대비 worst-case 회귀 여부

완료 기준:

- judge fail 0
- max wall이 timelimit보다 충분히 낮음
- max objective가 폭발봉으로 튀지 않음

## 조건 6: train 외 세트에서도 깨지지 않는다

train 20개만으로는 안전하다고 판단하지 않는다.

필수 검증 세트:

- `instances/gen`
- `instances/stress`
- `instances/tard`
- 가능하면 직접 생성한 random suite

판정 기준:

- fail count 증가 없음
- max wall 증가 없음 또는 허용 가능한 수준
- max objective 폭발 감소
- 평균 objective보다 worst-case 안정성 우선

완료 기준:

- 기존 solver 대비 fail이 증가하지 않는다.
- 새 selector가 특정 train 구조에만 맞춘 것이 아님을 확인한다.

## 조건 7: 새 알고리즘은 롤백 가능한 candidate generator여야 한다

MIP, LNS, tardiness-first repair는 core return path를 대체하지 않는다.

요구사항:

- 새 알고리즘은 candidate만 생성
- incumbent/gate/deadline 구조는 그대로 유지
- 실패 시 무시 가능
- env flag 또는 함수 단위로 비활성화 가능
- 제출 직전 문제 발생 시 쉽게 rollback 가능

완료 기준:

- 새 후보를 끄면 기존 안전 solver로 돌아간다.
- 새 후보가 실패해도 final answer가 나빠지지 않는다.

## 구현 순서

### P1-Foundation

목표: 현재 P1i/P1h 계열의 과최적화 분기를 일반화한다.

작업:

1. `simple_repair_floor`의 weight 구간 분기 제거
2. Phase-1 직후 `check_feasibility`로 증상 수집
3. `RepairDecision` 또는 유사 구조체 생성
4. `greedy`, `simple`, `emergency` repair 선택을 증상 기반으로 결정
5. 모든 repair 결과는 verified incumbent gate를 통과

완료 기준:

- train 20개 judge fail 0
- 기존 P1i 대비 head-to-head가 크게 후퇴하지 않음
- 위험 인스턴스 반복 실행 fail 0

### P2-Emergency Repair

목표: Z1 폭발을 직접 줄이는 좁은 후보를 추가한다.

후보:

- tardiness-first emergency repair
- tardy block fixed-layout reschedule
- violating/tardy block만 limited reinsert

제약:

- full rebuild 금지
- 시간 budget 작게 제한
- incumbent보다 좋아질 때만 채택

완료 기준:

- `prob_20`류 max objective 감소
- 기존 good cases fail/timeout 증가 없음

### P3-Bounded LNS

목표: verified incumbent 위에서만 제한적 LNS를 돌린다.

제약:

- small destroy size
- candidate마다 feasibility gate
- soft deadline 이후 새 iteration 금지
- incumbent보다 나쁘면 폐기

완료 기준:

- train 외 세트에서 fail 증가 없음
- worst-case objective 악화 없음

### P4-MIP Seed

목표: MIP는 full solver가 아니라 assignment/seed generator로만 사용한다.

후보:

- bay assignment MIP
- rough tardiness-aware assignment
- workload/preference balancing seed

제약:

- time budget 엄격 제한
- decode/gate 실패 시 무시
- incumbent 구조 유지

완료 기준:

- 특정 instance에서만 좋아지는 것이 아니라, 반복 worst-case가 안정적

## 성공 기준

최소 성공 기준:

- train 20개 judge fail 0
- 기존 P0 대비 judge fail 감소 유지
- baseline 대비 head-to-head 우위 유지
- 위험 인스턴스 반복 실행 fail 0

권장 성공 기준:

- train 외 세트 fail 증가 0
- max wall이 timelimit보다 3초 이상 낮음
- objective 폭발봉 빈도 감소
- `simple/greedy/emergency` 선택 근거가 로그로 설명 가능

## 롤백 기준

아래 중 하나라도 발생하면 해당 변경은 롤백한다.

- train 또는 gen/stress/tard에서 judge fail 증가
- 위험 인스턴스 반복 실행 중 1회 이상 timeout
- baseline 대비 loss 수 증가
- max objective가 기존 P1 대비 크게 악화
- selector가 사실상 train feature patch로 회귀

## 최종 원칙

새 알고리즘을 넣기 전의 기준은 다음 한 문장이다.

```text
새 후보가 실패해도 기존 verified incumbent를 deadline 안에 반환할 수 있는가?
```

이 질문에 항상 "예"라고 답할 수 있을 때만 MIP, LNS, portfolio를 추가한다.
