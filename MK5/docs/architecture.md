# MK5 Architecture

## Goal

`MK5`의 목적은 그래프를 사고 엔진으로 두지 않고, **장기 기억과 회수 인프라로 단순화한 뒤 LLM이 도구를 오케스트레이션하게 만드는 것**이다.

핵심은 다음과 같다.

- 하나의 대화 LLM이 응답 계획을 맡는다.
- 그래프는 사용자와 세계에 대한 장기 기억을 저장한다.
- 필요할 때 graph/search/file/document/image/terminal tool을 호출한다.
- 이전 턴에서 활성화된 그래프 문맥을 다음 턴으로 넘긴다.
- 매 턴 현재 질문 기준으로 그래프를 새로 활성화한다.
- 전체 도구 schema와 긴 tool history를 매 턴 밀어 넣지 않고, 압축된 도구 목록과 필요한 경우의 `tool_manual` 조회로 입력을 줄인다.

## Why This Architecture

이전 구조는 그래프 위에서 직접 사고하는 데 강점이 있었지만, 기본 응답 경로가 무거워지고 유지보수 부담도 커진다. `MK5`는 이 문제를 줄이기 위해 그래프의 책임을 다시 좁힌다.

즉 이 단계에서 그래프는:

- 생각하는 주체가 아니라
- 기억을 저장하고
- 다시 꺼내오고
- 사용자별로 누적하는 기반 구조다

LLM은 planner이자 최종 문장 생성자다. 오케스트레이터는 모델이 낸 JSON을 실행하고, 도구 실행이 필요한 요청에서 실제 실행 없이 완료 답변이 나가지 않도록 구조적으로 검증한다.

## High-level Flow

1. `user_id`, `session_id`, `message`를 받는다.
2. `user_anchor::<user_id>`가 없으면 만든다.
3. 사용자 발화를 해당 anchor 아래에 저장한다.
4. anchor 주변에서 작은 기억 요약을 읽어 온다.
5. 같은 세션의 이전 active graph context를 가져온다.
6. 현재 메시지와 이전 active graph context 일부를 기준으로 그래프를 새로 활성화한다.
7. LLM이 현재 메시지, 기억 요약, 이전 active graph context, 현재 graph activation을 바탕으로 답변을 계획한다.
8. 필요하면 그래프 조회, 검색, 시장 스냅샷, 파일 CRUD, 문서 읽기, 이미지 분석, 터미널 명령을 호출한다.
9. 도구 결과와 이번 턴의 발화/개념/검색 결과를 active graph context로 정리한다.
10. 유용한 새 사실은 다시 그래프에 저장한다.
11. 이번 턴의 active graph context를 다음 턴을 위해 세션별로 보관한다.

## Memory Structure

### 1. User anchors

- 사용자별 지속 anchor를 둔다.
- 같은 사용자의 기억을 세션을 넘어 같은 축에 누적한다.

### 2. Persistent graph repository

- SQLite 기반 그래프 저장소를 사용한다.
- 사용자 발화 흔적, 사실, 검색 기반 정보, correction 단서를 보관한다.

### 3. Retrieval-first usage

- 그래프는 기본 응답 때 전부 순회되지 않는다.
- 현재 질문과 가까운 기억만 요약해서 가져온다.

### 4. Active graph context

`MK5`는 장기 기억과 별도로, 세션 단위의 짧은 작업 기억을 둔다. 이것을 active graph context라고 부른다.

active graph context는 다음과 같은 항목에서 만들어진다.

- 현재 사용자 발화 노드
- 현재 발화에서 추출된 concept 노드
- memory summary에 들어간 사용자 기억
- graph search 결과 노드
- internet/latest search에 사용된 search node와 검색 결과
- file/document/image/terminal command 같은 도구 결과
- `.txt`, `.md`, `.markdown` 파일 읽기에서 추출된 file text activation 노드

이 context는 장기 기억 그 자체가 아니라, **이전 턴에서 실제로 활성화됐던 작업 문맥**이다. 따라서 모델에게는 `Previous active graph context`로 전달되지만, 항상 답변 근거로 쓰라는 의미는 아니다. 현재 질문과 관련 있을 때만 참고해야 한다.

현재 구현에서는 active graph context를 인메모리로 보관한다. 서버를 재시작하면 이 작업 문맥은 사라지지만, 장기 그래프 기억은 SQLite 저장소에 남는다.

### 5. Fresh graph activation

이전 active graph context를 들고 가는 것과 별개로, `MK5`는 매 턴 현재 질문 기준의 그래프 활성화를 새로 수행한다.

현재 구현에서는 아래 정보를 묶어 graph search query로 사용한다.

- 현재 사용자 메시지
- 이전 active graph context 일부

그 결과는 `Current graph activation`으로 모델 입력에 들어간다.

즉 한 턴의 모델 입력에는 서로 다른 두 그래프 문맥이 함께 들어간다.

```text
Previous active graph context
-> 이전 턴에서 실제로 활성화됐던 작업 문맥

Current graph activation
-> 현재 질문을 기준으로 새로 회수한 그래프 문맥
```

이 둘을 나누는 이유는, 단순히 이전 맥락을 들고 가는 것과 현재 질문에 맞춰 그래프를 다시 여는 일이 서로 다른 역할을 하기 때문이다.

## LLM Input Contract

`MK5`는 모델 입력을 의도적으로 짧게 유지한다. 현재 한 턴의 입력은 아래 요소로 구성된다.

```text
system prompt
user_payload
  - user_id / session_id
  - current message
  - recent dialogue, 기본 6개
  - memory summary
  - previous active graph context
  - current graph activation
  - weak file text activation from text file reads
  - compact tool definitions
  - compact tool history
  - output contract
```

### File text activation

`file_read`가 `.txt`, `.md`, `.markdown` 파일을 성공적으로 읽으면 MK5는 파일 본문을 그대로 장기 기억으로 저장하지 않는다. 대신 파일 텍스트에서 후보 노드를 뽑고 점수를 매긴 뒤, 하위 30%를 제거한 결과만 `file_context`와 concept node로 국소활성화 그래프에 임시 편입한다.

파일에서 온 노드는 사용자 발화에서 온 노드보다 약한 활성 강도로 들어간다.

```text
current user utterance / local nodes: 1.0
previous active graph nodes: 0.5
file text activation nodes: 0.25
```

이 값은 “파일을 읽었다”는 사실이 현재 작업에는 중요하지만, 사용자가 직접 말한 기억과 같은 강도로 장기 문맥을 끌어당기면 안 된다는 판단을 반영한다. 파일 text activation은 다음 턴의 작업 문맥에만 약하게 이어지며, 새 턴에서 다시 파일을 읽지 않으면 장기 기억 summary 후보로 고정되거나 계속 재전파되지 않는다.

긴 파일에서 후처리가 멈추지 않도록 파일 text activation 입력은 기본 8,000자로 제한한다. 또한 2,000자를 넘는 파일은 Sentence_Breaker 대신 더 가벼운 token fallback으로 후보를 만든다. 현재 기본값은 상위 70%, 최대 24개이며, 각각 `MK5_FILE_TEXT_NODE_KEEP_RATIO`, `MK5_FILE_TEXT_NODE_MAX_ITEMS`, `MK5_FILE_TEXT_ACTIVATION_MAX_CHARS`로 조정할 수 있다.

### Compact tool definitions

모든 도구는 기본적으로 모델에게 보인다. 대신 각 도구는 아래 정도만 짧게 전달된다.

- name
- short description
- argument key list
- required argument list
- optional argument shape hint
- manual address, 예: `tool_manual:file_update`

이 방식을 택한 이유는 도구를 숨기면 파일 작업 중 검색이 필요하거나, 검색 중 파일 확인이 필요한 복합 턴을 놓칠 수 있기 때문이다. 따라서 도구 선택지는 유지하고, 긴 schema만 늦게 읽는다.

### `tool_manual`

`tool_manual`은 도구 설명서 조회용 도구다.

모델이 특정 도구의 정확한 인자 구조를 모르면 다음처럼 먼저 설명서를 읽을 수 있다.

```json
{
  "tool": "tool_manual",
  "arguments": {
    "tool": "file_update"
  }
}
```

그 결과에는 해당 도구의 전체 description과 `input_schema`가 들어간다. 즉 기본 프롬프트에는 짧은 목록만 넣고, 자세한 schema는 필요한 도구에 대해서만 가져오는 구조다.

### Compact tool history

도구 실행 결과도 원문 전체를 그대로 다시 넣지 않는다. 예를 들어 파일 읽기는 path, 성공 여부, content preview, content length 중심으로 요약되고, 이미지 분석은 path, 이미지 크기, 사용 모델, description preview 중심으로 요약된다.

파일 전체 내용이나 긴 검색 결과가 계속 누적되면 모델이 현재 작업보다 과거 결과에 끌려갈 수 있기 때문에, tool history는 기본적으로 “다음 행동 판단에 필요한 정도”로 압축한다.

### Output contract

모델 출력은 JSON 하나로 고정된다.

- `final_answer`: 사용자에게 보여줄 최종 답변, 없으면 `null`
- `tool_calls`: 실행할 도구 호출 목록
- `final_answer_kind`: `answer`, `tool_completion`, `blocked`
- `completion_tools`: `tool_completion` 답변이 근거로 삼는 도구 이름 목록

파일 수정, 터미널 실행, 이미지 분석처럼 사용자가 실제 도구 수행을 요구한 턴에서는 도구가 성공하기 전의 “했습니다”류 답변을 완료로 보지 않는다. 최종 문장 자체는 LLM이 만들지만, 오케스트레이터가 도구 실행 여부와 성공 여부를 구조적으로 검증한다.

## Tooling

현재 `MK5`의 주요 도구군은 아래와 같다.

- graph memory: `graph_search`, `record_memory_correction`
- search: `internet_search`, `latest_search`, `market_snapshot`
- file CRUD: `file_create`, `file_read`, `file_update`, `file_delete`
- document: `document_read`
- image: `image_analyze`
- shell: `terminal_command`
- manual: `tool_manual`

`file_read`는 UTF-8 텍스트 파일만 읽는다. 이미지 파일은 `image_analyze`, PDF/DOCX는 `document_read`를 사용한다. 이 구분은 파일 확장자를 기반으로 도구가 안내하지만, 어떤 작업을 수행할지는 모델이 구조화된 tool call로 결정한다.

## Image and Upload Flow

이미지 분석은 대화 모델과 별도의 모델을 사용할 수 있다.

- `MK5_OLLAMA_MODEL_NAME`: 일반 대화 모델
- `MK5_OLLAMA_IMAGE_MODEL_NAME`: 이미지 분석 우선 모델
- `MK5_OLLAMA_IMAGE_FALLBACK_MODEL_NAME`: 우선 모델이 이미지 요청을 거부할 때의 대체 모델

UI에서도 대화 모델과 이미지 모델을 별도로 선택할 수 있다. 사용자가 클립 버튼으로 파일을 첨부하면 서버는 `/upload`로 파일을 받아 `.mk5_uploads/` 아래에 저장하고, 이후 대화에서는 업로드 경로를 `image_analyze`, `document_read`, `file_read` 같은 도구가 사용할 수 있다.

이 방식은 사용자가 다른 PC에서 브라우저로 접속하는 경우에도 경로 문자열만 넘기는 방식보다 안전하다. 실제 파일 바이트가 서버에 업로드되기 때문이다.

## What Changes In Practice

이 구조에서 바뀌는 것은 단순히 모듈 수가 아니라 응답의 기본 철학이다.

- 기본 경로에 thought loop를 두지 않는다.
- 기본 경로에 conclusion graph 생성도 두지 않는다.
- graph-to-language 계층을 기본값으로 두지 않는다.
- LLM이 planner 역할을 하고 그래프는 memory substrate가 된다.
- 그래프는 장기 기억 저장소이면서, 턴 단위로 활성화되는 working context를 제공한다.
- 프롬프트는 규칙을 계속 덧붙이는 방식보다, 짧은 기본 원칙과 구조적 guard로 유지한다.
- 문자열 신호나 임시 단어 목록으로 모델 행동을 틀어막기보다, JSON contract, tool schema, completion guard 같은 구조로 제어한다.

## Implementation Milestones

### Milestone 1

- 안정적인 user anchor 생성
- 발화 저장
- 그래프 기반 기억 요약 조회
- 단순 채팅 엔드포인트

### Milestone 2

- graph query tool 계약
- 실제 모델 백엔드 연동
- web search adapter

### Milestone 3

- fact write-back
- correction / conflict 저장 규칙
- memory browsing UI

### Milestone 4

- session-level active graph context
- fresh graph activation per turn
- active context persistence 여부 검토

### Milestone 5

- file CRUD 도구 분리
- PDF/DOCX 문서 읽기
- 이미지 분석 도구와 UI 첨부
- 대화 모델/이미지 모델 선택 분리
- compact tool definitions + `tool_manual`
- compact tool history
- `.txt`/`.md` 파일 읽기 결과의 약한 local graph activation
