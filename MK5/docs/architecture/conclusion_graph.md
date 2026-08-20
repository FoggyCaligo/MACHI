# MK5 ConclusionGraph 정책

작성: 2026-05-18  
상태: 정책 확정 초안 v1  
범위: Think activation, 결론 후보 단위, 입력 재진술 판정 기준

---

## 1. 핵심 결정

MK5에서 결론은 단일 노드가 아니다.

> 결론은 입력 그래프와 Goal 그래프 사이에서 선택된 국소 그래프다.

따라서 `물`, `소화기`, `정확성` 같은 노드 하나를 결론으로 보지 않는다.  
결론은 다음을 포함하는 answer-bearing subgraph다.

```text
input graph
  ↔ bridge / support / condition / conflict paths
  ↔ goal graph
```

즉 ThinkEngine의 목표는 높은 점수의 node를 찾는 것이 아니라, 사용자 입력과 Goal에 동시에 닿는 **ConclusionGraph**를 구성하는 것이다.

---

## 2. 현재 구현 범위

현재 구현은 최종 ThinkEngine이 아니라 **Think activation skeleton**이다.

포함:

```text
- input frontier / goal frontier 기반 2-hop activation
- 설정값 기반 hop 변경 가능
- input/goal activation meeting point 탐색
- meeting point anchor 기반 ConclusionGraph skeleton 생성
- restatement graph 제거가 아니라 score 강등
- opposite edge를 contrast_paths로 보존
- conflict edge를 conflict_paths / exception_hashes로 보존
- GraphToLang에 selected_graphs 보조 컨텍스트 제공
```

제외:

```text
- 명시적 TurnGoalView 생성
- TurnGoalView와 GlobalGoalGraph 충돌 재정렬 고도화
- evidence/source node 분리
- condition/action 역할 자동 분류
- GraphToLang의 완전한 selected_graphs 기반 전환
```

TODO:

```text
- TurnGoalView가 명시 구조로 만들어지면 GlobalGoalGraph와의 충돌 재정렬을 고도화한다.
- evidence/source node가 분리되면 evidence_energy와 support_paths를 payload가 아니라 source graph 기준으로 재계산한다.
```

---

## 3. Activation과 Conclusion의 분리

Activation은 node/edge 위로 퍼지는 임시 상태다.  
Conclusion은 그 activation 결과를 바탕으로 선택된 국소 그래프다.

```text
ActivationState
  - input_energy
  - goal_energy
  - context_energy
  - evidence_energy
  - conflict_pressure
  - novelty_score

ConclusionGraph
  - node_hashes
  - edge_ids
  - support_paths
  - goal_paths
  - conflict_paths
  - contrast_paths
  - role hash sets
```

따라서 activation 점수가 높은 노드가 곧 결론은 아니다.  
높은 activation은 conclusion graph를 구성하기 위한 후보 신호일 뿐이다.

---

## 4. Activation 전파 방식

ThinkEngine은 최소 두 방향에서 activation을 퍼뜨린다.

```text
1. Input frontier
   - LangToGraph에서 나온 입력 concept/slot 노드

2. Goal frontier
   - 현재 구현: GlobalGoalGraph
   - 최종 구조: TurnGoalView + GlobalGoalGraph
```

현재는 TurnGoalView를 명시 node/edge 구조로 만들지 않는다.  
대신 입력 그래프와 GlobalGoalGraph activation의 만남으로 현재 턴 목표를 간접 구성한다.

추가로 context/evidence source가 들어올 수 있다.

```text
3. Context frontier
   - previous_key_hashes
   - identity anchor 주변 구조
   - 현재 세션 주제

4. Evidence frontier
   - evidence/source node
   - 검색 또는 과거 검증 구조
```

Activation은 edge 구조를 따라 전파된다.

```text
propagated_energy =
  source_energy
  × edge.edge_weight
  × edge.trust_score
  × connect_type_gain
  × direction_gain
  × depth_decay
```

기본 전파 깊이는 2-hop이다.  
설정값 `THINK_ACTIVATION_HOPS`로 변경 가능하다.

이때 `connect_type`은 다음처럼 해석한다.

| connect_type | 전파 의미 |
|---|---|
| flow | 방향성 있는 의미 흐름. 정방향 강함, 역방향 약함. |
| neutral | 연상/근접/동시 등장. 양방향 가능하되 약함. |
| opposite | 대비축 활성. 삭제하지 않고 `contrast_paths`로 보존. |
| conflict | 결론 제거가 아니라 `conflict_pressure`, `conflict_paths`, `exception_hashes`로 기록. |

---

## 5. 결론 후보 단위

결론 후보는 노드가 아니라 `CandidateConclusionGraph`다.

초기 후보 그래프는 다음 조건에서 만들어진다.

```text
1. input frontier에서 도달 가능한 경로가 있다.
2. goal frontier에서 도달 가능한 경로가 있다.
3. input graph 내부 반복만으로 끝나지 않는다.
4. support/condition/action/conflict 중 하나 이상의 구조를 포함할 수 있다.
```

구현상으로는 다음 절차를 따른다.

```text
1. input_energy와 goal_energy를 모두 받은 meeting point를 찾는다.
2. meeting point를 conclusion graph anchor/core로 둔다.
3. input path + goal path + conflict/contrast path를 묶어 ConclusionGraph를 만든다.
4. 후보 그래프를 score 기준으로 정렬한다.
```

후보 그래프의 중심 노드는 있을 수 있다.  
그러나 중심 노드는 결론 자체가 아니라 결론 그래프의 anchor일 뿐이다.

---

## 6. ConclusionGraph 내부 역할

ConclusionGraph는 내부 node/edge 집합을 역할별로 볼 수 있다.

```text
core_hashes
  - 답변 중심 구조를 이루는 노드

condition_hashes
  - 조건, 범위, 전제 역할을 하는 노드

exception_hashes
  - 예외, 주의점, conflict를 표현하는 노드

action_hashes
  - 사용자가 실제로 취할 수 있는 실행 노드

bridge_hashes
  - 입력과 결론/Goal을 잇는 설명용 중간 노드
```

주의할 점:

- 역할은 `node_kind`가 아니다.
- 같은 노드라도 다른 ConclusionGraph 안에서는 다른 역할을 가질 수 있다.
- 역할은 graph 내부 위치, edge 방향, connect_type, path 성격으로 정해져야 한다.

현재 skeleton에서는 `core_hashes`, `bridge_hashes`, `exception_hashes`를 우선 채운다.  
`condition_hashes`, `action_hashes`는 필드만 유지하고 후속 정책/구현에서 채운다.

---

## 7. 입력 재진술의 정의

입력 재진술은 문자열 반복이 아니다.

> 입력 재진술은 입력 그래프의 구조를 거의 그대로 유지하고, Goal 방향의 새 구조를 만들지 못한 conclusion graph다.

재진술 후보의 구조적 특징은 다음과 같다.

```text
- node_hashes가 대부분 input_hashes 내부에 머문다.
- input 밖 확장 node가 없다.
- goal_paths가 없다.
- support_paths가 없다.
- condition/exception/action 구조가 없다.
```

현재 구현에서는 재진술 후보를 제거하지 않는다.  
대신 score와 uncertainty를 조정해 **강등**한다.

따라서 사용자의 입력 단어가 답변에 다시 등장한다고 해서 자동으로 재진술은 아니다.

예를 들어 사용자가 `Think와 Update의 책임 분리`를 물었다면, `Think`, `Update`, `책임 분리`는 답변에도 등장해야 한다.  
하지만 실제 결론 그래프는 다음처럼 입력 밖 구조를 만들어야 한다.

```text
Think
  → WorldGraph read-only
  → activation / path search
  → ConclusionGraph 생성

Update
  → WorldGraph write
  → EmptySlot fill
  → commit
  → trust/stability 조정

책임 분리
  → Think는 UpdateRequest만 반환
  → Update만 commit 가능
```

---

## 8. 실제 결론의 정의

실제 결론은 입력 그래프 밖으로 확장되어 GoalGraph와 정렬되는 새 구조다.

```text
ConclusionGraph =
  input graph와 연결되고,
  Goal graph와 정렬되며,
  support / condition / conflict / action 경로를 포함하는
  선택된 국소 그래프
```

예시:

```text
사용자: 불을 끄려면?

좋지 않은 결론 그래프:
  불
  끄다
  방법

좋은 결론 그래프:
  불 → 화재
  화재 → 진압
  진압 → 물
  진압 → 소화기
  기름 화재 → conflict → 물
  전기 화재 → conflict → 물
```

좋은 결론은 `물`이라는 노드 하나가 아니라, 조건과 예외를 포함한 화재 진압 국소 그래프다.

---

## 9. Conflict / Opposite 처리

Conflict는 결론 그래프를 무조건 제거하지 않는다.

```text
conflict edge
  → conflict_pressure 증가
  → conflict_paths 기록
  → exception_hashes 후보
```

예를 들어 `기름 화재 → conflict → 물`은 `물` 후보를 단순 삭제하는 것이 아니다.  
오히려 다음과 같은 답변 구조를 만들 근거가 된다.

```text
일반 화재에는 물이 도움이 될 수 있지만,
기름/전기 화재에는 물이 위험할 수 있으므로 화재 종류를 확인해야 한다.
```

Opposite 역시 제거하지 않는다.

```text
opposite edge
  → 낮은 activation으로 대비축 활성
  → contrast_paths 기록
```

---

## 10. Abstract node 처리

Abstract node는 결론 후보 자체가 아니다.  
하지만 bridge로는 사용할 수 있다.

```text
사과
배
귤
  → abstract fruit-like node
  → 과일
```

이 경우 abstract node를 답변의 중심으로 내세우지 않는다.  
다만 `사과 → 과일` 구조를 설명하는 bridge path에는 포함될 수 있다.

---

## 11. 코드 계약

초기 코드 계약은 다음 개념을 둔다.

```python
ActivationState
ReasoningStep
ReasoningPath
ConclusionGraph
RejectedConclusionGraph
ActivationResult
```

`ConclusionView`는 장기적으로 다음처럼 바뀐다.

```python
@dataclass
class ConclusionView:
    selected_graphs: list[ConclusionGraph]
    rejected_graphs: list[RejectedConclusionGraph]
    active_goal_view: GoalView | None
    turn_goal_view: TurnGoalView | None
    uncertainty: float
```

단기 호환을 위해 기존 필드 `nodes`, `edges`, `key_hashes`, `ref_hashes`는 유지한다.  
현재 GraphToLang은 기존 context를 유지하면서 `selected_graphs`를 보조 컨텍스트로 사용한다.  
하지만 GraphToLang의 최종 목표는 node list가 아니라 selected ConclusionGraph를 언어화하는 것이다.

---

## 12. 정책 v1

```text
1. Activation은 node/edge 단위로 퍼진다.

2. 결론 후보는 노드가 아니라 후보 국소 그래프다.

3. CandidateConclusionGraph는 input frontier와 goal frontier가 만나는 경로 묶음이다.

4. ConclusionGraph는 core, condition, exception, action, bridge 역할을 내부적으로 가진다.

5. 역할은 node_kind가 아니라 해당 conclusion graph 안에서의 위치와 edge 관계로 결정된다.

6. 입력 재진술은 입력 노드 반복이 아니라, 입력 그래프를 거의 그대로 복사하고 새 goal-aligned structure를 만들지 못한 그래프다.

7. 실제 결론은 입력 그래프 밖으로 확장되어 GoalGraph와 정렬되는 새 구조를 포함한다.

8. conflict는 결론 그래프를 제거하지 않고, exception/condition 구조로 포함될 수 있다.

9. opposite는 결론 그래프를 제거하지 않고, contrast path로 보존한다.

10. abstract node는 결론 자체가 아니라 conclusion graph 내부의 bridge로 사용한다.

11. GraphToLang은 장기적으로 노드 목록이 아니라 ConclusionGraph를 언어화해야 한다.
```

---

## 13. 다음 구현 단계

```text
1. TurnGoalView 계약 추가
2. TurnGoalView와 GlobalGoalGraph 충돌 재정렬 고도화
3. evidence/source node 분리
4. evidence_energy / support_paths를 source graph 기준으로 재계산
5. condition/action 역할 자동 분류
6. GraphToLang을 selected_graphs 기반으로 완전 전환
```

