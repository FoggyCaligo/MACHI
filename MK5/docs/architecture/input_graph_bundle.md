# MK5 InputGraphBundle 설계

작성: 2026-05-18
상태: 3단계 구현 기준 문서

## 배경

기존 흐름은 사용자 문장을 concept 후보 목록으로 바꾼 뒤, 각 ConceptPointer가 가진 LocalSubgraph를 TempThoughtGraph에 로드하는 방식이었다. 이 방식은 입력 단어들이 어떤 concept을 가리키는지는 전달하지만, 사용자 문장 자체가 하나의 임시 국소그래프 묶음이라는 사실을 명시하지 못한다.

앞으로 MK5의 입력 해석은 다음 방향을 따른다.

```text
사용자 문장
→ concept 후보 resolve
→ 각 concept의 LocalSubgraph 활성화
→ 문장 내부 임시 연결 생성
→ InputGraphBundle 생성
→ 목적 그래프와 함께 사고 루프에 투입
```

## 핵심 원칙

1. 사용자 입력은 노드 목록이 아니라 입력 국소그래프 묶음이다.
2. 각 direct concept은 자신을 중심으로 한 LocalSubgraph와 함께 활성화된다.
3. 문장 내부 인접 관계는 입력 의미를 구성하는 temporary edge로 유지된다.
4. 검색 결과 원문은 GraphToLang에 직접 전달하지 않는다.
5. 기존 profile, topic, user/AI identity, resolution provenance 정책은 유지한다.
6. 기존 graph에 없어서 EmptySlot으로 시작했더라도, 사고 루프에서 채워진 입력 concept은 keyword 후보 선정에서 direct 입력 성격을 잃지 않는다.
7. GraphToLang에는 key/reference 이분법보다 keyword와 중요도 점수를 함께 전달한다.
8. 입력 문장 edge는 WorldGraph에 커밋할 지식이 아니라 현재 턴 activation view다.

## 1단계 구현

```text
InputGraphBundle dataclass 추가
TranslatedGraph.input_bundle 추가
LangToGraph 마지막에 InputGraphBundle 생성
```

## 2단계 구현

2단계에서는 `InputGraphBundle`을 단순 보관 필드가 아니라 `TempThoughtGraph` 초기화 경로의 우선 입력으로 사용한다.

```text
TempThoughtGraph.load_from_translated(translated)
  ├─ translated.input_bundle 있음
  │   └─ load_from_input_bundle(bundle, empty_slots=translated.nodes의 EmptySlot)
  └─ translated.input_bundle 없음
      └─ 기존 ConceptPointer 순회 fallback
```

이렇게 하는 이유는 다음과 같다.

```text
- LangToGraph가 만든 입력 국소그래프 묶음을 Thought 단계에서 명시적으로 소비한다.
- 기존 nodes/edges 호환성은 유지한다.
- EmptySlot의 importance 값은 기존 EmptySlot 객체에 있으므로 그대로 보존한다.
- profile/topic/user-AI identity/provenance 로직은 건드리지 않는다.
```

## 3단계 구현

3단계에서는 `InputGraphBundle.sentence_edges`를 TempThoughtGraph의 런타임 activation edge로 로드한다.

```text
InputGraphBundle.sentence_edges
→ TempThoughtGraph._pending_sentence_edges
→ resolve 가능한 endpoint만 input_sentence temporary edge로 적재
→ EmptySlot이 fill_slot으로 채워지면 보류 edge 재시도
→ activation._spread()에서 input_sentence edge만 temporary 예외 전파 허용
```

이 edge는 다음 성격을 가진다.

```text
is_temporary=True
provenance_source=lang_to_graph
payload.runtime_view=True
payload.view_scope=input_sentence
```

따라서 입력 문장 edge는 다음에는 사용된다.

```text
- 입력 국소그래프 사이의 activation 전파
- 사용자의 현재 문장이 만든 임시 구조 보존
- EmptySlot ingest 이후 새로 채워진 노드와 기존 입력 concept의 연결 복원
```

반대로 다음에는 사용하지 않는다.

```text
- WorldGraph 영구 edge commit
- GraphToLang EvidenceEdges 직접 노출
- 사용자 identity/profile claim 저장
```

## InputGraphBundle 구조

```text
InputGraphBundle
  source
  center_hashes
  direct_hashes
  context_hashes
  empty_hints
  local_subgraphs
  sentence_edges
```

의미:

```text
source           원문
center_hashes    현재 입력을 대표하는 concept hash
DIRECT           현재 입력 surface가 직접 가리킨 concept
CONTEXT          local subgraph에서 의미적으로 끌려온 후보
empty_hints      아직 graph에 없는 concept hint
local_subgraphs  각 center concept의 국소그래프
sentence_edges   문장 내부 임시 연결 후보
```

## 아직 하지 않는 것

```text
TurnGoalGraph의 별도 명시 구조화
RecallNeed/SearchNeed 완전 분리
입력 문장 edge의 connect_type 구조 추론 고도화
input_sentence edge를 이용한 goal patch 생성 정책
```

## 이후 단계

다음 단계부터는 InputGraphBundle을 기반으로 TurnGoalGraph를 더 명시적으로 만들고, 현재 입력 그래프를 목적 그래프에 맞게 수정하는 GraphReasoningLoop로 확장한다.

최종 목표는 다음이다.

```text
InputGraphBundle
+ ProfileContextView
+ TopicContextView
+ IdentityContextView
+ LongTermGoalGraph
+ TurnGoalGraph
→ GraphReasoningLoop
→ ConclusionGraph
→ GraphToLang
```

