# MK4 Architecture

## 역할 분리

MK4는 세 계층의 책임을 분리한다.

```text
Framework
- raw user/assistant conversation 기록
- 실제 tool 실행과 결과 보존

LLM
- 응답 판단
- tool 선택
- semantic memory의 저장/수정 판단

Graph layer
- 지속 장기기억
- canonical node 재사용
- 동일 edge/assertion 강화
- revision history 보존
```

그래프는 추론 본체가 아니다. LLM이 필요할 때 명시적으로 읽고 쓰는 외부 장기기억이다.

## 요청 흐름

```text
User request
  ↓
raw user utterance 저장
  ↓
최근 dialogue context 구성
  ↓
LLM
  │
  ├─ 현재 문맥으로 답변 가능
  │     └─ answer
  │
  ├─ 최근 문맥 밖의 과거 정보 필요
  │     └─ recall_memory → tool_history → LLM
  │
  ├─ durable semantic information 발견
  │     └─ write_memory
  │
  └─ 기존 semantic memory가 outdated
        └─ recall_memory → revise_memory
  ↓
raw assistant utterance 저장
```

과거 사용자 정보나 이전 대화가 필요하지만 recent dialogue에 없다면 `recall_memory`를 사용해야 한다.

## Model-facing context

기본 model wrapper는 다음 구조만 전달한다.

```json
{
  "user_message": "...recent dialogue + current message...",
  "authorization_context": {},
  "tool_catalog": [],
  "tool_history": []
}
```

그래프 memory summary를 자동으로 주입하지 않는다.

따라서 persistent graph의 실제 내용은 `recall_memory`가 성공한 뒤 그 결과가 `tool_history`에 추가되었을 때만 모델에게 보인다.

요청 단위 scratchpad 계층도 두지 않는다.

- 현재 agent loop의 임시 실행 상태: `tool_history`
- 짧은 대화 문맥: recent dialogue
- 지속 장기기억: graph memory

으로 책임을 구분한다.

## Raw conversation graph

`GraphMemoryService.record_user_utterance()`는 다음을 기록한다.

```text
user_anchor
  └─ spoke → utterance
               └─ user_mentions_concept → concept
```

발화에서 별도 user fact를 자동 추출하지 않는다. 검색 snippet에서도 별도 search fact를 자동 추출하지 않는다.

raw graph의 목적은 semantic interpretation을 대신하는 것이 아니라 실제 대화/텍스트 흔적을 보존하고 graph search의 근거를 제공하는 것이다.

## Model-managed semantic memory

`ModelManagedGraphMemoryService`가 semantic memory 작업을 담당한다.

### Entity

모델이 label을 사용해 endpoint를 지정하면 graph layer가 canonical label을 계산한다.

```text
"Chess"
"  chess  "
      ↓
canonical: "chess"
      ↓
same semantic_entity node
```

이미 `recall_memory`가 반환한 entity라면 모델은 `node_id`를 재사용할 수 있다.

### Assertion

하나의 durable relationship은 canonical triple로 식별한다.

```text
subject_id | normalized_relation | object_id
```

이를 기반으로 하나의 `semantic_memory` assertion node를 만든다.

```text
user_anchor
   │ semantic_memory
   ▼
[semantic_memory assertion]
   ├─ memory_subject → [subject]
   └─ memory_object  → [object]
```

relation은 공백/하이픈 등을 정규화한 identifier로 저장한다.

### Duplicate reinforcement

동일한 subject/relation/object를 다시 저장하면 새 assertion node를 만들지 않는다.

`GraphRepository.add_edge()`의 동일 edge 계약에 따라 기존 edge의 `support_count`와 강도가 증가한다.

### Revision

`revise_memory`는 기존 assertion을 삭제하지 않는다.

```text
old assertion (is_active=false)
        │
        └─ superseded_by → new assertion
```

이렇게 현재 상태와 수정 이력을 동시에 보존한다.

## Memory tools

### recall_memory

Runtime tool 이름은 `graph_search`, model-facing 이름은 `recall_memory`다.

- no query/node id: 사용자 기억 browse
- query: 관련 graph search
- node_id: 특정 반환 노드 확장

현재 요청의 user id는 framework가 주입하므로 모델이 user id를 만들지 않는다.

### write_memory

하나의 durable semantic relationship을 저장하거나 기존 동일 assertion을 강화한다.

### revise_memory

기존 model-managed semantic assertion을 새로운 assertion으로 교체한다.

옛 `record_memory_correction`/자동 fact correction 경로는 사용하지 않는다.

## Search / file graph records

웹 검색 결과와 file text context는 출처 추적 및 현재 작업 문맥을 위해 graph에 기록될 수 있다. 이것들은 model-managed user semantic memory와 별개다.

텍스트 파일 context는 `suppress_from_summary`를 유지하며 semantic user memory로 자동 승격하지 않는다.

## Recent dialogue

Orchestrator는 최근 user/assistant 메시지를 `MK4_RECENT_MESSAGE_LIMIT` 범위에서 유지한다. 기본값 10개 메시지라면 약 5개 대화쌍이다.

최근 dialogue에 이미 필요한 내용이 있으면 별도의 long-term recall 없이 답할 수 있다. 그 범위를 벗어난 과거 정보가 필요하면 `recall_memory`를 사용한다.

## Failure contract

- 모델이 도구로 확인 가능한 정보를 사용자에게 다시 요구하지 않는다.
- 실제 tool/OS 실패 전에는 접근 불가를 가정하지 않는다.
- mutation은 실제 target/state를 확인한 뒤 실행하고 검증한다.
- 실패를 문자열 비교나 fallback으로 성공처럼 숨기지 않는다.
- 존재하지 않는 기억을 framework가 자동 주입해 모델 판단 실패를 가리지 않는다.

## Database transition

이 구조 이전의 DB에는 다음 legacy data가 남아 있을 수 있다.

- 자동 추출 `fact`
- `derived_fact` / `asserted_fact`
- old correction/replacement 관계
- recall-test interaction metadata

새 semantic-memory 구조를 검증할 때는 기존 DB를 백업하고 새 SQLite DB로 시작하는 것을 권장한다. 코드가 legacy node를 새 assertion으로 자동 migration하지는 않는다.
