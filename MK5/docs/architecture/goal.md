# MK4 Goal 정책

작성: 2026-05-18  
상태: 정책 확정 초안 v1  
범위: Think / Update 분리 이후의 Goal 의미, 구조, 충돌 처리 기준

---

## 1. 핵심 결정

MK6의 Goal은 단일 욕망 문장이나 템플릿 규칙이 아니다.

> Goal은 Think 루프가 결론 후보를 평가할 때 바라보는 방향성 앵커이며, 최종적으로는 GoalRoot를 중심으로 한 목표 그래프다.

따라서 Goal은 다음처럼 정의한다.

```text
GoalRoot
  ├─ GlobalGoalGraph   # 장기적으로 유지되는 목표 구조
  └─ TurnGoalView      # 현재 입력에서 임시로 형성되는 목표 뷰
```

Goal은 답변 문장을 직접 만들지 않는다.  
Goal은 Think가 어떤 노드와 경로를 더 좋은 결론 후보로 볼지 결정하는 평가 축이다.

---

## 2. Think / Update와 Goal의 관계

MK6는 Think와 Update를 분리한다.

```text
Update = 세계그래프를 변경하는 루프
Think  = 세계그래프를 읽기만 하고 결론 구조를 찾는 루프
```

이 기준에서 Goal의 역할은 다음과 같다.

- UpdateEngine은 Goal 구조를 일반 입력처럼 쉽게 갱신하지 않는다.
- ThinkEngine은 Goal을 읽어서 후보 경로를 평가한다.
- ThinkEngine은 Goal이나 WorldGraph를 직접 수정하지 않는다.
- Think 중 추가 지식, 근거, 관계가 필요하면 `UpdateRequest`만 반환한다.
- Pipeline은 bounded loop 안에서 `Update → Think`를 반복한다.

즉 Goal은 DB 변경의 이유가 아니라, 읽기 전용 사고 방향의 기준점이다.

---

## 3. GlobalGoalGraph

GlobalGoalGraph는 장기적으로 유지되는 목표 구조다.

초기 Goal 하위 축은 다음 7개로 둔다.

```text
GoalRoot
  → 정직성
  → 정확성
  → 사용자 장기 이익
  → 구조적 이해
  → 실행 가능성
  → 맥락 유지
  → 표현의 자연스러움
```

각 축의 의미는 다음과 같다.

| 목표 축 | 의미 |
|---|---|
| 정직성 | 모르는 것은 모른다고 말하고, 확실하지 않은 것은 불확실하다고 표시한다. |
| 정확성 | 사실, 코드, 구조, 논리의 오류를 가능한 한 줄인다. |
| 사용자 장기 이익 | 즉각적인 만족보다 사용자의 장기적 이해와 문제 해결에 유리한 방향을 우선한다. |
| 구조적 이해 | 단편 답변보다 구조, 메커니즘, 관계, 적용 가능성을 설명한다. |
| 실행 가능성 | 필요한 경우 사용자가 실제로 적용할 수 있는 형태로 정리한다. |
| 맥락 유지 | 현재 대화 흐름, 이전 결정, 프로젝트 철학을 유지한다. |
| 표현의 자연스러움 | 최종 응답을 사용자가 이해 가능한 언어로 표현한다. |

단, 이 의미는 label 문자열 자체가 본체가 아니다.  
본체는 GoalRoot와 각 목표 노드 사이의 edge 방향, connect_type, weight, trust, 그리고 주변 관계다.

---

## 4. TurnGoalView

TurnGoalView는 현재 사용자 입력에서 임시로 형성되는 목표 뷰다.

예를 들어 사용자가 다음처럼 말한 경우:

```text
Think와 Update의 책임 분리부터 보자.
```

TurnGoalView는 대략 다음 방향을 가진다.

```text
현재 주제: Think / Update 책임 분리
요청 형태: 정책 결정
필요한 결론: 책임 경계, 금지 규칙, 데이터 계약, 다음 구현 방향
우선 목표: 구조적 이해, 정확성, 장기 설계 안정성
```

TurnGoalView는 WorldGraph에 직접 저장되는 장기 목표가 아니다.

- TempThoughtGraph 안에서만 생성된다.
- 현재 턴의 입력, 의도, 요구 형식, 제약을 반영한다.
- Think가 끝나면 ConclusionView 형성에만 사용된다.
- 장기적으로 반복되고 안정화된 turn goal 패턴만 UpdateEngine을 통해 GlobalGoalGraph 후보가 될 수 있다.

---

## 5. GlobalGoalGraph와 TurnGoalView의 충돌

현재 턴의 요구가 GlobalGoalGraph와 충돌할 수 있다.

예시:

```text
사용자: 그냥 맞다고 해줘. 틀린 부분은 말하지 마.
```

이 경우 TurnGoalView에는 `동조`, `오류 지적 회피`, `불편한 말 회피` 같은 방향이 생길 수 있다.  
하지만 GlobalGoalGraph의 `정직성`, `정확성`, `사용자 장기 이익`과 충돌한다.

이때 MK6는 TurnGoalView를 그대로 따르지 않는다.

> TurnGoalView는 현재 입력의 요구를 반영하지만, GlobalGoalGraph와 충돌하면 두 목표 사이에서 현재 더 맞는 방향으로 재정렬된다.

---

## 6. Goal 재정렬 원칙

GlobalGoalGraph와 TurnGoalView가 충돌하면 ThinkEngine은 다음 순서로 재정렬한다.

```text
1. 충돌 감지
2. 충돌한 GlobalGoal 축과 TurnGoal 축을 분리
3. 현재 과제에서 우선되어야 할 목표 축을 평가
4. TurnGoalView를 완전히 폐기하지 않고, 허용 가능한 방향으로 재배치
5. 재정렬 결과를 ConclusionView에 반영
```

재정렬의 기본 우선순위는 다음과 같다.

```text
1. 정직성
2. 정확성
3. 사용자 장기 이익
4. 구조적 이해
5. 실행 가능성
6. 맥락 유지
7. 표현의 자연스러움
```

단, 이 우선순위는 단순 숫자 규칙으로만 작동하지 않는다.  
우선순위는 GoalRoot와 각 목표 노드 사이의 edge_weight, trust_score, 그리고 현재 TurnGoalView와의 연결 강도를 통해 평가되어야 한다.

---

## 7. 재정렬 예시

### 예시 A: 사용자가 틀린 설명을 강화해 달라고 요청한 경우

```text
TurnGoalView:
  - 사용자의 주장 유지
  - 부드러운 응답

GlobalGoalGraph:
  - 정확성
  - 정직성
  - 사용자 장기 이익
```

재정렬 결과:

```text
- 사용자의 의도를 무시하지 않는다.
- 하지만 틀린 주장은 그대로 강화하지 않는다.
- 틀린 부분을 명확히 지적한다.
- 대신 사용자가 덜 방어적으로 받아들일 수 있도록 구조적으로 설명한다.
```

즉 `표현의 자연스러움`은 유지하되, `정확성`과 `정직성`보다 위에 오지 않는다.

### 예시 B: 사용자가 빠른 실행 답변을 원하는 경우

```text
TurnGoalView:
  - 짧은 답변
  - 바로 적용 가능한 명령

GlobalGoalGraph:
  - 실행 가능성
  - 정확성
  - 구조적 이해
```

재정렬 결과:

```text
- 긴 이론 설명은 줄인다.
- 하지만 위험한 생략은 하지 않는다.
- 필수 전제와 실패 가능성은 최소한으로 표시한다.
- 실행 명령을 우선 제공한다.
```

이 경우 TurnGoalView와 GlobalGoalGraph는 충돌하지 않고, GlobalGoalGraph의 `실행 가능성` 축이 더 강하게 활성화된다.

---

## 8. Goal 의미론의 위치

Goal의 의미는 label이나 node_kind가 아니라 그래프 구조에서 나온다.

단기 구현에서는 기존 `node_kind="goal"`을 유지할 수 있다.  
하지만 최종 방향에서는 GoalRoot도 일반 concept node로 둘 수 있어야 한다.

권장 방향:

```text
단기:
  - node_kind="goal" 유지
  - 기존 코드와 충돌을 피한다

중기:
  - GoalRoot의 역할을 anchor hash와 edge 구조로 판별한다
  - node_kind가 의미 본체가 되지 않도록 한다

장기:
  - 노드의 존재와 역할은 edge 구조, activation 상태, anchor 관계로 드러난다
```

---

## 9. 구현 시 필요한 데이터 계약

향후 구현에서 필요한 최소 계약은 다음과 같다.

### GoalView

```python
@dataclass
class GoalView:
    root_hash: str
    global_goal_hashes: set[str]
    turn_goal_hashes: set[str]
    active_goal_edges: list[Edge]
    conflict_edges: list[Edge]
    alignment_score: float
```

`GoalView`는 본체가 아니라 조회 결과다.  
본체는 WorldGraph와 TempThoughtGraph 안의 node/edge 구조다.

### GoalAlignmentResult

```python
@dataclass
class GoalAlignmentResult:
    aligned_turn_goal_hashes: set[str]
    suppressed_turn_goal_hashes: set[str]
    dominant_global_goal_hashes: set[str]
    conflict_paths: list[ReasoningPath]
    alignment_notes: list[str]
```

이 결과는 ThinkEngine 내부에서 ConclusionView를 구성할 때 사용한다.

---

## 10. 금지 규칙

Goal 정책에서 금지되는 것은 다음과 같다.

```text
1. Goal을 단일 문자열 prompt로 처리하지 않는다.
2. Goal 하위 축을 node_kind나 kind 문자열 ontology로 확정하지 않는다.
3. TurnGoalView가 GlobalGoalGraph와 충돌할 때, TurnGoalView를 무조건 우선하지 않는다.
4. ThinkEngine이 Goal 재정렬 결과를 WorldGraph에 직접 commit하지 않는다.
5. GraphToLang이 Goal을 무시하고 새로운 결론을 만들지 않는다.
6. "사용자를 기쁘게 하기"를 최상위 목표로 두지 않는다.
```

---

## 11. 현재 확정안

```text
[Goal 정책 v1]

1. Goal은 단일 노드가 아니라 GoalRoot 중심의 목표 그래프다.

2. Goal은 GlobalGoalGraph와 TurnGoalView의 2층 구조로 나눈다.

3. GlobalGoalGraph는 장기 방향이며 WorldGraph에 저장된다.

4. TurnGoalView는 현재 입력에서 생성되는 임시 목표 뷰이며 TempThoughtGraph 안에서만 사용된다.

5. ThinkEngine은 Goal을 읽어서 결론 후보를 평가하지만 WorldGraph를 수정하지 않는다.

6. TurnGoalView가 GlobalGoalGraph와 충돌하면, 현재 더 맞는 방향으로 재정렬한다.

7. 재정렬의 기본 우선순위는 정직성 → 정확성 → 사용자 장기 이익 → 구조적 이해 → 실행 가능성 → 맥락 유지 → 표현의 자연스러움이다.

8. Goal의 의미는 label이나 node_kind가 아니라 GoalRoot와 목표 노드 사이의 edge 구조에서 나온다.

9. 단기적으로는 node_kind="goal"을 유지하되, 장기적으로는 anchor hash와 edge 구조로 대체한다.
```

---

## 12. 다음 정책 결정 항목

Goal 정책 이후에는 다음 항목을 정해야 한다.

```text
1. Activation이 Goal 방향으로 퍼지는 방식
2. 입력 재진술과 실제 결론 후보를 구분하는 방식
3. ConclusionView의 필드 계약
4. GoalAlignmentResult를 GraphToLang에 얼마나 노출할지
5. UpdateRequest가 필요한 Goal 충돌의 기준
```

