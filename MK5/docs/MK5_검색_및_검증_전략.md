# MK5 검색 및 검증 전략

## 1. 목표
MK5의 검색은 “모르면 인터넷 검색해서 답한다”가 아니다.
검색의 목적은 **현재 그래프가 비어 있는 부분만 국소적으로 보강**해서,
그 결과를 다시 그래프에 넣고 사고를 재개하는 것이다.

즉 검색은 answer-generation 보조가 아니라,
**graph completion / evidence enrichment**에 가깝다.

---

## 2. 기본 원칙

### 2-1. graph-first
- search 필요 판단은 그래프/사고 계층이 한다.
- 모델은 search 여부를 최종 결정하지 않는다.

### 2-2. slot-level search
- 질문 전체를 한 방에 search하지 않는다.
- 질문에서 entity / aspect slot을 뽑고,
- 그래프가 비어 있는 slot만 search한다.

### 2-3. provenance-preserving
- 검색 결과는 반드시 provider / source_provenance / trust_hint와 함께 들어간다.

### 2-4. error-visible
- 검색 실패는 실패처럼 보인다.
- provider error와 no result를 구분한다.

### 2-5. grounded response only
- grounding되지 않은 slot은 단정하지 않는다.

---

## 3. 권장 파이프라인
1. `QuestionSlotPlanner`
   - entities 추출
   - aspects 추출
2. `GraphCoverageEvaluator`
   - covered_slots 계산
   - missing_slots 계산
3. `MissingSlotSearchPlanner`
   - missing slot만 query로 변환
4. backend execution
5. search ingest
6. re-activation
7. re-thinking
8. conclusion / verbalization

---

## 4. search need 판정 기준
### search 필요 true
- 새 entity가 들어왔는데 grounding 없음
- 비교 축(aspect)이 늘었는데 해당 aspect coverage 없음
- conflict가 있는데 corroboration 가능한 대상임
- slot planner 실패 + multi-entity/multi-aspect 요청

### search 필요 false
- 현재 질문의 모든 slot이 충분히 covered
- 검색으로 얻을 수 없는 대상이고 내부 근거가 충분함
- 단순 memory probe / acknowledgment

---

## 5. conflict double-check 정책
현재 대화에서 나온 중요한 방향:

> 기존 그래프와 충돌하면,
> 검색 가능한 대상에 대해 external search로 더블체크하고,
> corroboration 되면 trust를 올리고,
> threshold를 넘으면 graph update를 수행한다.

이건 매우 좋은 방향이다.
다만 정보는 “사용자 vs 세계”로 이분화하기보다,
**모든 정보가 대상(entity)에 종속되고, 출처/검증 가능성이 별도 축으로 붙는다**고 보는 편이 더 일관된다.

즉:
- entity에 대한 claim
- provenance
- corroboration 가능성
- trust dynamics
를 함께 본다.

---

## 6. 디버그에 반드시 보여야 하는 것
- `planning_attempted`
- `query_triggered`
- `requested_slots`
- `covered_slots`
- `missing_slots`
- `issued_slot_queries`
- `grounded_terms`
- `missing_terms`
- `provider_errors`
- `error`

---

## 7. 앞으로의 고도화 방향
### 1차
- slot planner 안정화
- fail-open to search
- provider error visibility

### 2차
- trusted_search 다중 backend
- pairwise / grouped slot query batching
- `missing_aspects` 계산

### 3차
- conflict-driven corroboration
- search 결과 기반 trust 상승 / revision trigger
- post-search synthesis 강화

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
