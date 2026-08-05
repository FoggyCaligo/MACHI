# MK5 Architecture Draft

## Goal

`MK5`의 목적은 그래프를 사고 엔진으로 두지 않고, **장기 기억과 회수 인프라로 단순화하는 것**이다.

핵심은 다음과 같다.

- 하나의 대화 LLM이 응답 계획을 맡는다.
- 그래프는 사용자와 세계에 대한 장기 기억을 저장한다.
- 필요할 때 graph tool, web search tool 같은 도구를 호출한다.

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
5. LLM이 현재 메시지와 기억 요약을 바탕으로 답변을 계획한다.
6. 필요하면 그래프 조회, 웹 검색, 파일 도구를 호출한다.
7. 유용한 새 사실은 다시 그래프에 저장한다.

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

## What Changes In Practice

이 구조에서 바뀌는 것은 단순히 모듈 수가 아니라 응답의 기본 철학이다.

- 기본 경로에 thought loop를 두지 않는다.
- 기본 경로에 conclusion graph 생성도 두지 않는다.
- graph-to-language 계층을 기본값으로 두지 않는다.
- LLM이 planner 역할을 하고 그래프는 memory substrate가 된다.

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


