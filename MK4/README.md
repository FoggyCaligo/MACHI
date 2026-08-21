# MK4

`MK4`는 **LLM이 판단과 도구 오케스트레이션을 담당하고, 그래프는 외부 장기기억 저장소로 사용하는 실행형 개인 AI**다.

## 핵심 구조

```text
현재 사용자 입력
+ 최근 대화 문맥
+ 도구 목록 / 현재 tool history
        ↓
       LLM
        │
        ├─ 과거 기억 조회 → recall_memory
        ├─ 장기 기억 저장 → write_memory
        ├─ 장기 기억 수정 → revise_memory
        └─ 파일 / 웹 / 터미널 등 일반 도구
```

그래프의 내용을 매 턴 자동으로 모델에게 주입하지 않는다. 과거 사용자 정보나 이전 대화가 필요한데 최근 대화 문맥에 없다면 모델은 `recall_memory`를 사용해야 한다.

## 기억의 두 층

### Raw conversation graph

Framework가 사용자/assistant 발화를 자동으로 기록한다. 사용자 발화는 text graph의 concept 노드들과 연결되지만, 발화에서 별도의 `fact`를 자동 추출하지 않는다.

이 층의 목적은 **무슨 대화가 실제로 있었는지 보존하는 것**이다.

### Model-managed semantic memory

오래 유지할 가치가 있는 사용자 사실, 선호, 결정, 목표, 관계, 프로젝트 문맥은 모델이 `write_memory`로 직접 기록한다.

```text
[user/entity]        [entity]
       \              /
        \            /
       [semantic_memory]
          relation=...
```

- 동일한 canonical entity는 기존 노드를 재사용한다.
- 동일한 subject / relation / object 기억을 다시 저장하면 assertion을 복제하지 않고 기존 edge의 `support_count`를 강화한다.
- 기존 기억이 바뀌면 `revise_memory`가 이전 assertion을 inactive history로 남기고 새 assertion과 `superseded_by`로 연결한다.
- 질문, 기억 확인 요청, 단순 tool instruction 자체는 semantic memory로 저장하지 않는다.

## 기억 도구

### `recall_memory`

지속 그래프를 조회한다.

- 인자 없이 호출하면 사용자 기억을 넓게 탐색한다.
- `query`로 관련 기억을 검색한다.
- 반환된 `node_id`로 해당 노드를 확장한다.
- `write_memory` / `revise_memory`에서 기존 entity를 재사용할 때 반환된 node id를 사용할 수 있다.

### `write_memory`

하나의 durable semantic relationship을 저장하거나 동일 기억을 강화한다.

### `revise_memory`

`recall_memory`에서 확인한 기존 semantic memory를 새 관계로 대체한다. 과거 assertion은 삭제하지 않는다.

## 모델 입력

기본 Ollama 모델 래퍼가 매 라운드 전달하는 구조 데이터는 다음뿐이다.

```text
user_message
authorization_context
tool_catalog
tool_history
```

장기기억의 자동 summary는 포함하지 않는다. 실제 `recall_memory` 결과는 다른 도구 결과와 동일하게 `tool_history`에 나타난다.

최근 대화는 orchestrator가 `MK4_RECENT_MESSAGE_LIMIT` 범위에서 `user_message` 안의 최근 dialogue context로 제공한다. 기본값 10개 메시지라면 사용자/assistant 한 쌍 기준 약 5턴이다.

요청 단위 scratchpad는 사용하지 않는다. 현재 작업에서 얻은 결과는 현재 agent loop의 `tool_history`, 최근 대화는 recent dialogue, 지속해야 하는 정보는 graph memory가 맡는다.

## 도구 실행

모델에게 노출된 도구는 MK4 자신의 실행 능력으로 취급한다. 파일, 웹, 이미지, 문서, 터미널 등 실제 작업이 필요한 요청은 해당 도구를 호출하고 실제 성공/실패를 근거로 완료 여부를 판단한다.

세부 tool schema는 기본 prompt에 모두 넣지 않고 `tool_manual`을 통해 필요할 때 조회한다.

파일/터미널 변경은 실제 대상을 먼저 확인하고 변경 후 검증한다. 실제 도구 또는 OS가 실패하면 그 실패를 그대로 드러낸다.

## 파일과 외부 정보

- 텍스트 파일: `file_read`, `file_create`, `file_update`, `file_delete`
- 파일 탐색: `file_search`
- PDF/DOCX: `document_read`
- 이미지: `image_analyze`
- 쉘/OS 작업: `terminal_command`
- 외부 조사: `web_research`
- 시세/환율: `market_snapshot`

텍스트 파일을 읽을 때 만들어지는 file context 노드는 작업 문맥 추적용이며 사용자 semantic memory와 별개다.

## 저장소

기억 그래프는 SQLite `GraphRepository`에 저장된다. 사용자별 anchor를 중심으로 raw utterance, concept, semantic entity, semantic memory 등의 노드와 관계를 유지한다.

현재 semantic-memory 구조로 전환하기 전의 DB에는 자동 추출 fact나 옛 correction 구조가 남아 있을 수 있다. 새 구조를 평가할 때는 기존 DB를 백업한 뒤 새 DB로 시작하는 것을 권장한다.

## 설계 원칙

- Framework는 **대화가 있었다는 사실**을 자동 기록한다.
- LLM은 **무엇을 장기적으로 기억할지** 판단한다.
- Graph layer는 **중복 없는 저장과 관계 정합성**을 책임진다.
- 장기기억은 자동으로 모델에게 주입하지 않는다.
- 최근 문맥 밖의 과거 정보가 필요한 경우 `recall_memory`를 사용한다.
- 실패를 fallback이나 문자열 휴리스틱으로 성공처럼 숨기지 않는다.
