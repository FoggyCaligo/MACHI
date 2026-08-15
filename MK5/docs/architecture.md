# MK5 Architecture Draft

## Goal

`MK5`의 목적은 그래프를 사고 엔진으로 두지 않고, **장기 기억과 회수 인프라로 단순화하는 것**이다.

핵심은 다음과 같다.

- 하나의 대화 LLM이 응답 계획을 맡는다.
- 그래프는 사용자와 세계에 대한 장기 기억을 저장한다.
- 필요할 때 graph tool, web search tool 같은 도구를 호출한다.
- 이전 턴에서 활성화된 그래프 문맥을 다음 턴으로 넘긴다.
- 매 턴 현재 질문 기준으로 그래프를 새로 활성화한다.

## Why This Architecture

이전 구조는 그래프 위에서 직접 사고하는 데 강점이 있었지만, 기본 응답 경로가 무거워지고 유지보수 부담도 커진다. `MK5`는 이 문제를 줄이기 위해 그래프의 책임을 다시 좁힌다.

즉 이 단계에서 그래프는:

- 생각하는 주체가 아니라
- 기억을 저장하고
- 다시 꺼내오고
- 사용자별로 누적하는 기반 구조다

## High-level Flow

1. `user_id`, `session_id`, `message`를 받는다.
2. `user_anchor::<user_id>`가 없으면 만든다.
3. 사용자 발화를 해당 anchor 아래에 저장한다.
4. anchor 주변에서 작은 기억 요약을 읽어 온다.
5. 같은 세션의 이전 active graph context를 가져온다.
6. 현재 메시지와 이전 active graph context 일부를 기준으로 그래프를 새로 활성화한다.
7. LLM이 현재 메시지, 기억 요약, 이전 active graph context, 현재 graph activation을 바탕으로 답변을 계획한다.
8. 필요하면 그래프 조회, 웹 검색, 파일 도구를 호출한다.
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
- internet search에 사용된 search node와 검색 결과
- workspace file, terminal command 같은 도구 결과

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

## What Changes In Practice

이 구조에서 바뀌는 것은 단순히 모듈 수가 아니라 응답의 기본 철학이다.

- 기본 경로에 thought loop를 두지 않는다.
- 기본 경로에 conclusion graph 생성도 두지 않는다.
- graph-to-language 계층을 기본값으로 두지 않는다.
- LLM이 planner 역할을 하고 그래프는 memory substrate가 된다.
- 그래프는 장기 기억 저장소이면서, 턴 단위로 활성화되는 working context를 제공한다.

## First Implementation Milestones

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


