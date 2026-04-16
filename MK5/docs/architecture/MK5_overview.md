# MK5 overview

## 한 문장 요약
MK5는 입력을 의미블록으로 분해해 하나의 세계 그래프에 누적하고, 그 그래프의 국부 활성화 위에서 사고를 전개한 뒤 마지막에만 언어화하는 인지형 대화 시스템이다.

---

## MK4와의 차이
MK4의 중심은 revisable memory substrate 였다.
MK5의 중심은 **세계 그래프 기반 판단**이다.

즉,
- MK4 = evidence / memory / correction 중심
- MK5 = graph / activation / intent / conclusion 중심

둘은 단절이라기보다, 저장층에서 판단층으로 무게중심이 올라간 관계다.

---

## 핵심 구성요소
### 1. ingest
- 입력을 바로 답변하지 않는다.
- `InputSegmenter`가 의미블록을 만든다.
- `GraphIngestService`가 node / edge / pointer / event를 기록한다.

### 2. world graph
- user / assistant / search / file가 같은 그래프 안에 들어간다.
- 다만 `source_type × claim_domain`에 따라 trust가 다르다.

### 3. thought view
- 전체 그래프 전체를 사고에 쓰지 않는다.
- 현재 입력과 연결된 국부 부분만 `ThoughtView`로 활성화한다.

### 4. thinking
- contradiction 감지
- trust 하락
- revision review
- 필요 시 shallow merge 또는 edge deactivation
- intent snapshot 결정

### 5. conclusion
- 본체는 설명형 `CoreConclusion`
- `activated_concepts` / `key_relations`는 참조 목록
- 행동형은 `DerivedActionLayer`로 얇게 파생

### 6. verbalization
- conclusion을 한국어 응답으로 바꾸는 단계
- 언어화는 사고가 아니다

---

## 현재 구현 수준
현재 MK5는 “완성된 인지 엔진”은 아니다.
하지만 최소한 아래 루프는 닫혀 있다.

- user ingest
- activation
- thinking
- search enrichment
- re-thinking
- conclusion
- action layer
- verbalization
- assistant ingest

즉, **세계 그래프에 들어온 정보가 다시 다음 사고의 재료가 되는 최소 루프**는 이미 연결되어 있다.

---

## 현재 가장 중요한 미완료
- trusted_search 기반 검색 레이어
- `tools/ollama_client.py` 실구현
- `graph_commit_service.py`
- `edge_update_service.py`
- 더 깊은 개념 재구성형 merge

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
