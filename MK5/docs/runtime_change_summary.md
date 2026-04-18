# Runtime Change Summary

업데이트: 개념 분화 + 주제 따라가기 재도입 버전

## 왜 다시 넣었는가
슬림 런타임만으로는 다음 문제가 남아 있었습니다.
- 답변이 질문의 주제를 따라가기보다, 현재 활성 그래프 전체를 따라감
- 핵심 concept가 너무 많이 잡혀 search obligation과 응답 초점이 퍼짐
- 현재 입력 전체가 핵심 topic처럼 보이는 현상

## 이번 변경 핵심
### 1. 개념 분화 재도입
- 파일: `core/thinking/concept_differentiation_service.py`
- 목적:
  - partial_reuse 반복 → `concept/flow`
  - shared neighbor → `concept/neutral`
  - 강한 contradiction → `concept/conflict`
- 효과:
  - 개념 간 구조가 다시 살아나고,
  - 평평한 concept 나열을 줄일 수 있습니다.

### 2. 주제 따라가기 재도입
- 파일: `core/thinking/intent_manager.py`
- 목적:
  - 현재 topic term과 이전 topic term의 연속성 계산
  - `continued_topic / related_topic / shifted_topic` 구분
- 효과:
  - 답변과 explanation summary가 현재 질문의 초점을 더 잘 따라갑니다.

### 3. topic term 추출 축소
- 파일: `core/activation/activation_engine.py`
- 목적:
  - 전체 concept를 모두 current topic으로 보지 않고,
  - 질문 문장과 seed activation을 중심으로 정렬
- 효과:
  - `안녕`, `나는`, `지금` 같은 주변 concept가 topic 중심을 잡아먹는 현상을 줄임

### 4. 검색 의무 축소
- 파일: `core/search/search_need_evaluator.py`
- 목적:
  - graph total이 아니라 현재 topic term 기준으로 grounding 필요 여부 판단
  - 현재 턴 생성 노드를 grounding 근거에서 제외
- 효과:
  - search need가 현재 질문의 핵심 개념 중심으로 좁혀짐

### 5. 활성 concept 요약 축소
- 파일: `core/thinking/conclusion_builder.py`
- 목적:
  - 디버그/행동 레이어에 보이는 activated concepts를 핵심 위주로 제한
- 효과:
  - reasoning/answer layer가 지나치게 많은 concept에 끌려가지 않음

## 현재 정책
- concept는 그래프에 넓게 들어갈 수 있다.
- 하지만 topic following / search obligation / answer focus는 좁게 잡는다.
- 즉,
  - 저장은 넓게
  - 판단은 좁게
  가 현재 원칙이다.
