# MK4 TurnGoalView 설계

작성: 2026-05-18
상태: 3단계 구현 기준 문서

## 배경

MK6에는 이미 GlobalGoalGraph가 있다. 이 그래프는 정직성, 정확성, 장기 이익, 구조적 이해 같은 장기 목적 축을 WorldGraph 안에 bootstrap한다.

하지만 이번 턴에서 사용자가 무엇을 요구했는지에 대한 목적 구조는 아직 명시적으로 분리되어 있지 않았다. 그 결과 ThoughtEngine은 장기 목적 노드와 입력 그래프를 연결하지만, 이번 턴 목적을 별도 view로 들고 있지 못했다.

## 결정

3단계에서는 LongTermGoalGraph를 새로 만들지 않는다. 기존 GlobalGoalGraph를 장기 목적 그래프로 유지한다.

새로 추가하는 것은 `TurnGoalView`다.

```text
LongTermGoalGraph = 기존 GoalView / GlobalGoalGraph
TurnGoalView     = 이번 턴 입력 그래프에서 생성된 목적 view
```

## TurnGoalView 역할

TurnGoalView는 WorldGraph에 저장되는 본체가 아니다. 이번 턴 ThoughtEngine이 읽는 projection이다.

포함 정보:

```text
source
input_center_hashes
input_direct_hashes
input_context_hashes
empty_hints
long_term_goal_hashes
turn_goal_hash
```

의미:

```text
source                사용자 원문
input_center_hashes   이번 입력을 구성하는 concept 중심
input_direct_hashes   사용자가 직접 말한 concept
input_context_hashes  local graph에서 의미적으로 끌려온 후보
empty_hints           아직 graph에 없는 concept hint
long_term_goal_hashes 장기 목적 축 hash
turn_goal_hash        이번 턴 목적을 대표하는 임시 goal hash
```

## 중요한 제약

1. TurnGoalView는 문자열 intent type enum이 아니다.
2. recall/search/explain 같은 응답 타입을 여기서 만들지 않는다.
3. TurnGoalView는 현재 입력 그래프와 장기 목적 그래프를 이어주는 임시 목적 view다.
4. 기존 profile, topic, user-AI identity, provenance 로직은 유지한다.

## 3단계 구현 범위

```text
TurnGoalView dataclass 추가
build_turn_goal_view() 추가
ThoughtEngine.think() 시작 시 TurnGoalView 생성
TempThoughtGraph에 turn goal 임시 node 로드
input direct concept을 turn goal에 임시 연결
```

아직 하지 않는 것:

```text
GraphPatch reasoning loop
goal alignment scoring
RecallNeed/SearchNeed 완전 분리
TurnGoalView 기반 ConclusionGraph 품질 개선
```

## 이후 단계

4단계부터 GraphReasoningLoop는 다음 입력을 함께 사용한다.

```text
InputGraphBundle
ProfileContextView
TopicContextView
IdentityContextView
LongTermGoalGraph
TurnGoalView
```

목표는 현재 입력 그래프를 TurnGoalView와 LongTermGoalGraph에 더 잘 맞는 방향으로 patch하는 것이다.

