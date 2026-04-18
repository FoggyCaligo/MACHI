# MK5 런타임 철학과 답변 계약

이 문서는 현재 MK5가 반드시 지켜야 하는 철학과 응답 계약을 정리한다.
코드 수정은 이 문서와 충돌하지 않아야 한다.

## 1. 그래프 우선
- 장기 상태의 중심은 append-only 문자열 로그가 아니라 그래프다.
- 존재는 node, 관계와 상태는 edge가 맡는다.
- 현재 입력은 그래프에 적재될 수 있지만, **그 자체가 곧 기존 근거는 아니다.**

## 2. 현재 입력은 접근 키, 근거는 별개
- 현재 턴에서 만들어진 node는 기본적으로 `mention-only`일 수 있다.
- `mention-only` 노드는 존재하더라도 direct access 성공으로 치지 않는다.
- access 성공 조건은 **node 존재**가 아니라 **usable grounding 존재**다.

## 3. 질문 대상 grounding 우선
- search need는 그래프 총량이 아니라 **질문 대상 grounding 존재 여부**로 판단한다.
- 아래 상태는 모두 search 필요 후보다.
  - node 없음
  - node는 있으나 mention-only
  - grounded이나 stale 가능성 있음
  - grounded이나 현재 질문 요구를 충족하지 못함

## 4. search-before-think
- search는 think 사후 보강이 아니라, 가능하면 think 이전의 graph completion 단계여야 한다.
- 목표 순서는 다음과 같다.
  1. 입력
  2. 입력 의미 단위 추출
  3. direct access
  4. 부족한 의미 단위 search
  5. search ingest / 약한 edge 연결
  6. think
  7. verbalize

## 5. 의미 단위 추출 원칙
- 1차 후보 추출은 정규식/기계적 분해로 넓게 한다.
- LLM은 새 노드를 대량 생성하는 대신,
  - 현재 의도
  - 핵심 keyword
  - 배경 keyword
  - 업데이트 필요 정보 종류
  를 라벨링하는 데 사용한다.
- 문장 전체를 그대로 노드화하는 방향은 지양한다.

## 6. 답변 계약
- grounded evidence가 없으면, 모른다고 답한다.
- search가 실패했거나 근거가 부족하면, 추측으로 빈칸을 메우지 않는다.
- 모델 일반지식은 evidence보다 우선할 수 없다.
- evidence에 없는 세부사항은 단정하지 않는다.

## 7. assistant answer 처리 원칙
- assistant의 자유 생성 문장 전체를 다시 그래프 근거로 넣지 않는다.
- 필요한 경우에는 lightweight snapshot만 별도로 남긴다.
  - tone_hint
  - topic_terms
  - answer_goal

## 8. 다이어트 원칙
- 핫패스에는 꼭 필요한 레이어만 둔다.
- 실패를 가리는 fallback/helper/보조 LLM 레이어를 늘리지 않는다.
- 문제를 증상 패치로 덮지 않고, 실행 경로를 단순화해 원인을 제거한다.
