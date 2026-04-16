# Thought flow

## 현재 사고 루프
### 1. 입력 ingest
`GraphIngestService`
- chat_message 저장
- graph_event 기록
- meaning block 분해
- node 재사용/생성
- edge / pointer 반영

### 2. activation
`ActivationEngine`
- 현재 입력 기준 seed block 생성
- seed node 탐색
- local node / edge / pointer 수집
- `ThoughtView` 생성
- `PatternDetector`로 활성 패턴 추가

### 3. thinking
`ThoughtEngine`
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- `IntentManager`
- `ConclusionBuilder`

순서상 의미:
- 먼저 구조 충돌을 본다
- 그다음 trust와 revision 후보를 반영한다
- 필요 시 shallow merge / deactivation을 수행한다
- 그 상태를 바탕으로 현재 intent snapshot을 고른다
- 마지막에 explanation 중심 conclusion을 만든다

### 4. search enrichment
`SearchSidecar`
- 필요한 경우 외부 검색을 시도한다
- 검색 결과도 같은 그래프에 낮은 trust로 반영된다
- 이후 activation / thinking을 한 번 더 수행할 수 있다

### 5. verbalization
- `DerivedActionLayer` 생성
- verbalizer가 최종 사용자 응답 생성
- assistant 응답도 다시 그래프에 반영된다

---

## IntentManager의 현재 의미
현재 intent manager는 완전한 “목표 생성기”가 아니다.
지금 사이클의 그래프 상태를 보고,
무엇을 우선하는 사고로 볼지 정하는 **snapshot manager**다.

현재 판단 근거:
- contradiction 수
- revision 수
- inquiry / relation block 수
- edge / pointer / pattern 수
- 최근 assistant turn의 intent snapshot과의 overlap

현재 산출값:
- `live_intent`
- `snapshot_intent`
- `previous_snapshot_intent`
- `shifted`
- `continuation`
- `shift_reason`
- `sufficiency_score`
- `stop_threshold`
- `should_stop`

---

## 아직 남은 것
- drive → live intent → snapshot intent로 이어지는 더 깊은 의도 함수
- 실패 히스토리에 따라 stop threshold가 더 장기적으로 조정되는 구조
- multi-cycle thought loop

---

## 2026-04-16 최신 동기화

### 이번 코드 반영 사항
- `ModelFeedbackService`가 `ChatPipeline.process()`에 연결되어, 최종 `thought_view` 기준으로 기존 엣지에 대한 support/conflict 피드백을 `GraphCommitService`로 커밋한다.
- `ModelEdgeAssertionService`를 신규 도입하고 `ChatPipeline.process()`에 연결했다.
  - 모델이 `from_node_id / to_node_id / edge_family / connect_type` 형태의 새 엣지를 제안하면 실제 그래프에 생성/강화한다. 세부 메모가 필요하면 `relation_detail` 또는 `data/note`에 보조 정보만 남긴다.
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
