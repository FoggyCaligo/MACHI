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

### 3. Think→Search 루프 (최대 `_THINK_SEARCH_MAX_LOOPS` = 3회)

```
for 최대 3회:
    ThoughtEngine.think()   ← CoreConclusion 생성 (루프 내부 전용)
    SearchSidecar.run()     ← CoreConclusion으로 검색 방향 결정
    검색 결과 없으면 break  ← 현재 thought_result가 최종
    검색 결과 Ingest → Re-Activation → 다음 회차
else (break 없이 완주):
    최종 Think 1회 추가     ← 마지막 enriched 뷰 반영
```

`ThoughtEngine` 내부 순서:
- `ContradictionDetector`: 구조 충돌 감지
- `TrustManager`: trust/pressure 갱신
- `StructureRevisionService`: shallow merge / deactivation 실행
- `IntentManager`: 현재 intent snapshot 선택
- `ConclusionBuilder`: `CoreConclusion` 생성 (루프 내 SearchSidecar 방향 결정용)

`CoreConclusion`의 역할:
- 루프 내부 전용 중간 산물
- SearchSidecar가 검색 필요 여부·범위를 판단하는 데 사용
- Verbalization 계층에는 노출되지 않음

### 4. ConclusionView 구성
`ConclusionViewBuilder`
- 입력: 최종 ThoughtView + ThoughtResult
- 사용자 입력 핵심 키워드(topic_terms)를 기준으로 노드/엣지 룰 기반 선별
  - 노드: is_active=True + trust_score ≥ threshold + 키워드 매칭 또는 1-hop 이웃
  - 엣지: 선별된 노드 간 + connect_type ≠ 'conflict' + trust_score ≥ threshold
  - 순서: trust_score 내림차순 → logical_sequence
- Verbalization 계층이 참조하는 유일한 결론 구조 (CoreConclusion 완전 대체)

### 5. verbalization
- `ConclusionView`를 입력으로 `DerivedActionLayer` 생성
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
- ConclusionViewBuilder의 키워드 매칭 정교화 (의미적 유사도 기반 확장)

---

## 2026-04-20 최신 동기화

### 이번 코드 반영 사항

#### Think→Search 루프 구조화
- `chat_pipeline.py`의 기존 "1회 하드코딩 루프"를 `_THINK_SEARCH_MAX_LOOPS = 3`회 일반 루프로 교체
- Python `for-else` 패턴 사용: break 없이 완주 시 최종 Think 1회 추가 실행
- 루프 내 Ollama 타임아웃 3배 상향:
  - `OLLAMA_TIMEOUT_SECONDS`: 120s → 360s
  - `QUESTION_SLOT_PLANNER_TIMEOUT_SECONDS`: 30s → 90s
  - `SEARCH_COVERAGE_REFINER_TIMEOUT_SECONDS`: 30s → 90s
  - `REQUEST_TIMEOUT_MS`: 300,000ms → 900,000ms
- 루프 밖 단일 실행 타임아웃(Verbalizer, ModelEdgeAssertion)은 유지

#### ConclusionView 도입
- `core/entities/conclusion_view.py`: 새 결론 구조 엔티티
- `core/thinking/conclusion_view_builder.py`: 룰 기반 노드/엣지 선별 빌더
  - 사용자 입력 topic_terms 기준 키워드 매칭 + 1-hop 확장
  - trust_score threshold 기반 필터링
  - connect_type='conflict' 엣지 제외
- Verbalization 계층 전체(`verbalizer`, `template_verbalizer`, `ollama_verbalizer`, `action_layer_builder`, `meaning_preserver`)가 `ConclusionView`만 참조하도록 교체
- `CoreConclusion`은 루프 내부 전용으로 격리 (SearchSidecar 방향 결정에만 사용)
- debug payload: `core_conclusion` → `conclusion_view` (요약 형태)

#### LLM 호출 최소화
- **ModelFeedbackService 제거**: `chat_pipeline.py`에서 완전 제거. `ContradictionDetector`/`TrustManager`가 그래프 기반으로 동일 역할 수행.
- **SearchScopeGate 임베딩 교체** (`core/search/search_scope_gate.py` 전면 재작성):
  - Ollama `/api/embed` 사용 (기본 모델: `nomic-embed-text`)
  - query 임베딩 vs 활성 노드 임베딩(max 30개) 코사인 유사도 최댓값 계산
  - max_sim ≥ `SCOPE_GATE_SIMILARITY_THRESHOLD`(0.65) → 그래프 충분 → 검색 불필요
  - max_sim < threshold → 외부 검색 필요
  - `OllamaClient.embed()` 신규 추가 (`tools/ollama_client.py`)
  - fail-open: 임베딩 실패 시 `SearchScopeGateError` → `scope_gate_error` 노출 후 SlotPlanner 경로로 진행
  - `SearchSidecar._can_attempt_scope_gate()`: 채팅 모델명 무관, 항상 True

### connect_type 정책(현재)
- 현재 허용 집합: `flow`, `neutral`, `opposite`, `conflict`.
- 모델이 허용 집합 밖의 connect_type을 제안하면:
  - 엣지는 `neutral`로 저장
  - `relation_detail.proposed_connect_type`에 후보를 보존
  - `relation_detail.proposal_reason`으로 승격 후보 근거를 남김
- 즉, 즉시 스키마 확장 없이도 "모델의 새 타입 제안"을 축적할 수 있다.

### 디버그/운영 관측 포인트
- chat debug payload:
  - `model_edge_assertion`
  - `search.need_decision.scope_gate` (max_similarity, node_count, threshold)
  - `search.need_decision.scope_gate_error`
- activation metadata:
  - `concept_hop_edge_count`

### 설정값(config.py)
- `EMBEDDING_MODEL_NAME` (기본: `nomic-embed-text`)
- `EMBEDDING_TIMEOUT_SECONDS` (기본: 10s)
- `SCOPE_GATE_SIMILARITY_THRESHOLD` (기본: 0.65)
- `MODEL_EDGE_ASSERTION_TIMEOUT_SECONDS`
- `MODEL_EDGE_ASSERTION_TEMPERATURE`
- `MODEL_EDGE_ASSERTION_NUM_PREDICT`

### 운영 전제조건
```bash
ollama pull nomic-embed-text
```

### 현재 남은 이슈
- Windows 환경에서 `.pytest_tmp` 권한 문제로 일부 pytest 세션 종료 정리가 실패할 수 있다.
- 따라서 현재 검증은 `py_compile` 중심 + 제한된 스모크 확인 기준이다.

### 다음 우선 작업
1. ConclusionViewBuilder 키워드 매칭 정교화 (의미적 유사도 확장)
2. `model_edge_assertion`의 실제 대화 E2E 검증 및 회귀 테스트 추가
3. `proposed_connect_type` 누적-승격 정책(임계치 기반) 구현
