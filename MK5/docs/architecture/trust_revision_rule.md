# Trust revision rule

## 현재 기본 원칙
MK5는 새 구조가 들어와도 기존 구조를 즉시 부수지 않는다.
기본은 구조 보존이고,
반복 충돌이 누적될 때만 trust를 낮추고 revision을 검토한다.

---

## 현재 trust 하락 트리거
`ContradictionDetector`가 감지한 signal이 들어오면 `TrustManager`가 아래 값을 누적한다.

- `trust_score` 하락
- `conflict_count` 증가
- `contradiction_pressure` 증가

그리고 아래 중 하나를 만족하면 revision candidate로 올린다.

- pressure >= `2.0`
- conflict_count >= `2`
- trust_score <= `0.42`

즉, 현재는 **조금 얕은 누적량**에서 revision review 대상으로 올라간다.

---

## revision review 단계
`StructureRevisionService`는 revision candidate를 검토한다.

현재 우선순위:
1. shallow duplicate merge 가능 여부 확인
2. merge가 아니면 deactivation 필요 여부 확인
3. 둘 다 아니면 pending 유지

---

## 현재 merge 정책
현재 merge는 **revision 단계에서만** 일어난다.

즉,
- ingest 직후 자동 merge는 하지 않는다.
- revision candidate review 중에만 merge를 시도한다.
- 기준은 duplicate-like node에 한정한다.

현재 merge 허용 조건:
- `node_kind` 동일
- 그리고 아래 중 하나
  - `address_hash` 동일
  - `normalized_value` 동일
  - alias set 교집합 존재

의미:
- trigger는 얕게
- merge 허용 범위는 보수적으로

---

## deactivation 기준
merge로 처리하지 못한 edge는 아래 기준으로 deactivate를 검토한다.

- trust_score <= `0.2`
- contradiction_pressure >= `4.0`
- conflict_count >= `4`

그 전까지는 revision pending으로 유지될 수 있다.

---

## 아직 안 된 것
- relation retyping
- merge 후보 설명성 강화
- merge / deactivate를 묶는 graph commit service
- 더 깊은 구조 재조직형 revision

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
