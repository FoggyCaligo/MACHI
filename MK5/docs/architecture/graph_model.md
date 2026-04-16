# Graph model

## 기본 원칙
MK5의 세계 그래프는 문장 저장소가 아니라, 재사용 가능한 의미 단위를 누적하는 구조다.

- 원문 전체 = provenance
- 그래프 노드 = 의미블록 / 개념 단위
- 엣지 = 관계 / support / conflict / revision 압력
- 포인터 = partial reuse / 기존 노드 참조

---

## node
대표 필드:
- `address_hash`
- `node_kind`
- `raw_value`
- `normalized_value`
- `trust_score`
- `stability_score`
- `payload`
- `is_active`

의미:
- 같은 입력 전체를 그대로 저장하는 것이 아니라
- 재사용 가능한 단위가 node로 들어간다.

---

## edge
대표 필드:
- `source_node_id`
- `target_node_id`
- `edge_type`
- `edge_weight`
- `support_count`
- `conflict_count`
- `contradiction_pressure`
- `trust_score`
- `revision_candidate_flag`
- `is_active`

현재 엣지는 단순 연결선이 아니라,
**지지와 충돌의 누적량**을 함께 가진다.

---

## pointer
pointer는 partial reuse를 표현한다.
즉, 새 입력이 기존 노드 일부를 재사용할 때
중복 복사 대신 참조를 남긴다.

현재 역할:
- 부분 포함 관계 기록
- 추후 merge / rewrite 시 재배선 대상

---

## graph event
graph event는 그래프가 어떻게 바뀌었는지의 이력이다.

예:
- ingest root event
- trust update event
- edge revision pending
- edge deactivation
- intent snapshot decided
- node merged

즉, 세계 그래프 본체와는 별도로
**변화의 로그**를 남긴다.

---

## 현재 구조 재작성 수준
현재 가능한 재작성은 아래 수준이다.

1. trust 하락
2. revision candidate 표기
3. revision review
4. duplicate-like 노드 shallow merge
5. edge deactivation
6. pointer rewrite

아직 안 된 것:
- 공통부 추출 기반 상위 개념 재조직
- relation retyping 고도화
- graph commit orchestration

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
