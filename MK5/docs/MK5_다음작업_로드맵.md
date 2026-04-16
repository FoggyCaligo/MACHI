# MK5 다음작업 로드맵

기준 시점: 2026-04-15

## A. 지금 바로 해야 하는 것

### A1. search 오류 계약 정리
목표:
- slot planner / query planner / backend 오류를 fail-open하지 않고 명시적으로 surface
- provider failure와 no-result를 분리
- transport / timeout / 4xx / 5xx를 debug와 응답 계약에서 구분

현재 상태:
- "검색이 필요한데 모델이 미선택"인 경우는 이미 사용자 오류로 반환된다.
- `result_count=0`은 `no_evidence_found`로 verbalization까지 전달된다.
- 하지만 `QuestionSlotPlanner` 실패 중 일부는 아직 `slot_planner_failed_needs_grounding`으로 남아 있다.

완료 조건:
- planner JSON 오류, backend transport 오류, provider no-result가 서로 다른 상태로 기록된다.
- `search.error`와 `search.provider_errors`의 의미가 명확해진다.
- "오류를 오류로 돌려준다"는 Machi 철학과 실제 런타임이 일치한다.

### A2. groundedness 억제 강화
목표:
- grounded term이 없는 항목은 단정하지 않기
- missing aspect가 있으면 그 aspect에 대한 단정 금지
- verbalization이 search gap을 자연스럽게 감추지 못하게 하기

완료 조건:
- 일부 항목만 검색으로 확인된 경우, 나머지를 자연스럽게 메우는 식의 설명이 줄어든다.
- `missing_terms`, `missing_aspects`가 실제 응답 어조를 제어한다.
- search evidence ingest 뒤 재평가된 covered/missing 상태가 답변 제어에 반영된다.

### A3. 테스트와 계약 동기화
목표:
- 현재 search / debug payload 기준으로 unit / integration 테스트 정리
- 오래된 fixture와 dataclass 필드 불일치 제거
- 문서와 코드가 같은 상태를 바라보게 만들기

완료 조건:
- `SearchEvidence`의 현재 필드 기준으로 테스트가 정리된다.
- search debug 관련 회귀를 자동으로 잡을 수 있다.
- 최소 pytest 루틴이 바로 실행 가능하다.

## B. 그 다음 해야 하는 것

### B1. trusted-search backend 확장
현재:
- backend는 `CompositeSearchBackend`로 Wikipedia + web search를 함께 시도한다.
- 하지만 provider 선택 정책, trust policy 연결, provider별 오류 구분은 아직 초기형이다.

다음:
- 다중 provider
- source provenance / trust 계층 연결
- dedup / ranking / provider별 실패 기록 강화

### B2. post-search synthesis 강화
목표:
- 검색 결과를 단순 나열이 아니라 비교 / 요약 / 차이 구조로 재조직
- entity별 aspect 비교를 conclusion에 더 직접 반영

예시:
- 구조
- 방어력
- 기동성
- 사용 맥락

현재 메모:
- slot planner는 `search_aspects`와 `comparison_axes`를 분리할 수 있으므로,
  이후 synthesis는 검색축이 아니라 비교축 중심으로 답변을 조직해야 한다.

### B3. graph semantics 강화
목표:
- typed edge semantics 확장
- `InputSegmenter`를 concept / relation block 수준으로 고도화
- contradiction / revision이 더 구조적으로 동작하게 만들기

## C. 코어 빈칸 채우기

### C1. `graph_commit_service.py`
필요한 이유:
- merge / deactivate / rewrite / trust update를 하나의 구조 변경 흐름으로 안정적으로 묶을 orchestration이 필요하다.

### C2. `edge_update_service.py`
필요한 이유:
- relation refinement / retyping / support accumulation을 별도 책임으로 끌어내야 한다.

### C3. `meaning_preserver.py` 또는 동등 계층
필요한 이유:
- conclusion과 최종 사용자 응답 사이에서 의미 보존과 과장 억제를 감시할 계층이 필요하다.

## D. 지금은 미뤄도 되는 것
- `tools/response_runner.py`
- `app/orchestrator.py`
- `app/routes/chat.py`
- `core/verbalization/llm_verbalizer.py`

이 파일들은 지금 당장 실구현하는 것보다, 현재 루프와 오류 계약을 먼저 정리하는 편이 더 중요하다.

## E. 추천 작업 순서
1. `SearchSidecar`의 fail-open 잔여 정책 제거 또는 축소
2. provider failure / no-result / timeout 구분 추가
3. groundedness 억제 강화
4. search 관련 테스트 정리
5. trusted-search backend 확장
6. `graph_commit_service.py` 설계 초안

---

## 2026-04-16 최신 동기화

### 이번 코드 반영 사항
- `ModelFeedbackService`가 `ChatPipeline.process()`에 연결되어, 최종 `thought_view` 기준으로 기존 엣지에 대한 support/conflict 피드백을 `GraphCommitService`로 커밋한다.
- `ModelEdgeAssertionService`를 신규 도입하고 `ChatPipeline.process()`에 연결했다.
  - 모델이 `from_node_id / to_node_id / edge_family / connect_type / relation_detail.kind` 형태의 새 엣지를 제안하면 실제 그래프에 생성/강화한다.
- `ActivationEngine`에 concept 2-hop 확장을 추가했다.
  - seed의 1-hop concept 인접 노드에 대해 concept 엣지를 한 번 더 확장해 사고 뷰에서 상위/유사 개념 연결이 덜 잘리지 않게 했다.
- concept 엣지 우선 정렬을 유지해 `max_neighbor_edges` 한도에서 relation 엣지에 밀리는 문제를 완화했다.

### connect_type 정책(현재)
- 현재 허용 집합: `flow`, `neutral`, `opposite`, `conflict`.
- 모델이 허용 집합 밖의 connect_type을 제안하면:
  - 엣지는 `neutral`로 저장
  - `relation_detail.proposed_connect_type`에 후보를 보존
  - `relation_detail.proposal_reason`으로 승격 후보 근거를 남김
- 즉, 즉시 스키마 확장 없이도 "모델의 새 타입 제안"을 축적할 수 있다.

### 디버그/운영 관측 포인트
- chat debug payload:
  - `model_feedback`
  - `model_edge_assertion`
- activation metadata:
  - `concept_hop_edge_count`

### 설정값(config.py)
- `MODEL_FEEDBACK_TIMEOUT_SECONDS`
- `MODEL_FEEDBACK_TEMPERATURE`
- `MODEL_FEEDBACK_NUM_PREDICT`
- `MODEL_EDGE_ASSERTION_TIMEOUT_SECONDS`
- `MODEL_EDGE_ASSERTION_TEMPERATURE`
- `MODEL_EDGE_ASSERTION_NUM_PREDICT`

### 현재 남은 이슈
- Windows 환경에서 `.pytest_tmp` 권한 문제로 일부 pytest 세션 종료 정리가 실패할 수 있다.
- 따라서 현재 검증은 `py_compile` 중심 + 제한된 스모크 확인 기준이다.

### 다음 우선 작업
1. `model_edge_assertion`의 실제 대화 E2E 검증 및 회귀 테스트 추가
2. `proposed_connect_type` 누적-승격 정책(임계치 기반) 구현
3. connect_type/semantics가 contradiction/revision 규칙에 미치는 영향 고도화
