# MK5 전체 정리

기준 시점: 2026-04-15

## 1. 한 문장 정의
MK5는 입력을 바로 응답으로 보내는 챗봇이 아니라, 입력을 그래프에 반영하고 `ThoughtView` 위에서 사고한 뒤 마지막에만 언어화하는 graph-first cognition system이다.

## 2. 현재 상태 요약

### Implemented
- SQLite schema / repository / unit-of-work 기반 저장 구조
- `GraphIngestService`
- `ActivationEngine` + `ThoughtView`
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- `IntentManager`
- `ConclusionBuilder`
- `DerivedActionLayer`
- `TemplateVerbalizer`
- `OllamaVerbalizer`
- `SearchSidecar`
- `QuestionSlotPlanner`
- `SearchNeedEvaluator`
- `SearchQueryPlanner`
- assistant reply 재ingest
- Flask chat API / UI

### Partial
- 입력 분절
  - `InputSegmenter`는 동작하지만 아직 concept / relation block 단위의 정밀 분해보다는 초기 surface segmentation에 가깝다.
- revision / merge
  - revision 단계 shallow merge는 있으나 typed relation 기반 구조 수정까지는 아직 아니다.
- search
  - 질문을 entity / aspect slot으로 쪼개고 missing slot만 검색하는 흐름은 들어왔지만, backend는 아직 Wikipedia 중심이다.
- verbalization groundedness
  - search 상태는 전달되지만 missing term / missing aspect 억제가 아직 충분히 강하지 않다.

### Planned
- `graph_commit_service.py`
- `edge_update_service.py`
- `meaning_preserver.py`
- trusted-search 다중 backend
- conflict-driven external corroboration
- post-search synthesis 강화

## 3. 최근 반영된 정리
- 문자열 기반 재사용 fallback 제거
  - durable node reuse는 `address_hash` 기준만 사용
- `ConclusionBuilder`의 intent fallback 제거
  - `intent_snapshot`이 없으면 명시적으로 오류 처리
- `TemplateVerbalizer`의 사용자 응답 fallback 제거
- stopword 기반 token drop 제거
- punctuation-only 입력의 강제 statement fallback 제거
- search debug UI와 backend payload shape 불일치 수정
- 검색이 필요한데 모델이 선택되지 않은 경우
  - 조용히 넘어가지 않고 사용자에게 바로 이해 가능한 오류로 반환
- `QuestionSlotPlanner`가 `search_aspects`와 `comparison_axes`를 분리
  - 검색에 필요한 factual axis와 최종 답변 비교축을 구조적으로 나눈다
- `result_count=0`일 때 `no_evidence_found`를 search context와 verbalization에 전달
  - 검색 시도만 되었고 근거가 확보되지 않은 상태를 숨기지 않게 한다
- search evidence ingest 뒤 groundedness를 한 번 더 재평가
  - 검색 전 missing slot 상태를 그대로 끌고 가지 않는다

## 4. 검색의 현재 상태

### 현재 루프
1. coarse search need 판단
2. `QuestionSlotPlanner`가 entity / aspect slot 추출
3. `SearchNeedEvaluator`가 covered / missing slot 계산
4. `SearchQueryPlanner`가 missing slot만 query로 변환
5. backend search 실행
6. search evidence ingest
7. re-activation / re-thinking
8. verbalization

### 현재 장점
- search가 질문 전체를 뭉뚱그려 처리하지 않고, graph gap 기준으로 동작하기 시작했다.
- planner 실패와 actual query execution이 `planning_attempted`, `query_triggered`로 구분되어 보인다.
- 검색이 필요한데 selectable model이 없으면 사용자 오류로 바로 surface된다.
- UI debug도 `requested_slots`, `covered_slots`, `missing_slots`, `issued_slot_queries`를 현재 payload 기준으로 표시한다.
- slot planner가 search용 축과 비교용 축을 분리해서 내보낼 수 있다.
- 검색 결과가 0건이면 `no_evidence_found` 상태가 verbalization에 전달된다.

### 현재 한계
- `QuestionSlotPlanner` 실패 중 일부는 아직 `slot_planner_failed_needs_grounding`으로 fail-open된다.
  - Machi가 지향하는 "오류는 담백하게 오류로 반환" 철학과 완전히 일치하지 않는 잔여 정책이다.
- provider failure와 no-result가 아직 명확히 분리되지 않았다.
- `grounded_terms`, `missing_terms`, `missing_aspects`는 구조적으로 전달되지만 억제 강도와 응답 품질은 더 다듬어야 한다.
- provenance / trust 계층이 전체 trust policy와 완전히 연결되지는 않았다.

## 5. 지금 가장 중요한 판단
지금 MK5에서 가장 중요한 일은 철학을 더 확장하는 것이 아니라, 이미 만들어진 루프와 계약을 안정화하고 그 위에서 그래프 의미 구조를 더 정교하게 만드는 것이다.

우선순위는 다음 순서가 맞다.

1. 현재 루프와 계약 안정화
2. search / verbalization groundedness 강화
3. graph semantics 강화
4. placeholder 서비스 실구현
5. 문서와 코드 sync 유지

## 6. 최신 우선순위

### P0
- planner / backend 오류를 fail-open하지 않고 명시적 오류 계약으로 정리
- search failure vs no-result 구분
- `provider_errors` / transport failure visibility 복구
- missing term / missing aspect가 있을 때 hallucination 억제 강화
- UI / API / debug payload 계약 고정
- pytest 기반 테스트 루틴 정리

### P1
- trusted-search backend 확장
- post-search synthesis 강화
- typed edge semantics 확장
- `InputSegmenter`를 concept / relation block 쪽으로 고도화

### P2
- `graph_commit_service.py` 실구현
- `edge_update_service.py` 실구현
- `meaning_preserver.py` 또는 동등 계층 추가
- conflict-driven external corroboration과 graph update 연결

## 7. placeholder / 미완성 상태

### 실제 placeholder
- `tools/response_runner.py`
- `app/orchestrator.py`
- `app/routes/chat.py`
- `core/update/graph_commit_service.py`
- `core/update/edge_update_service.py`
- `core/verbalization/llm_verbalizer.py`
- `core/verbalization/meaning_preserver.py`

### placeholder는 아니지만 아직 초기형
- search backend 전체
- `InputSegmenter`
- verbalization groundedness 제어
- post-search synthesis

## 8. 지금 MK5를 한 문장으로 말하면
MK5는 방향성만 있는 프로젝트가 아니라, graph-first cognition이라는 방향을 실제 동작 루프로 바꾸기 시작한 초기 시스템이며, 이제부터의 핵심은 그 루프를 Machi 철학에 맞게 더 엄격하고 정직하게 만드는 것이다.
