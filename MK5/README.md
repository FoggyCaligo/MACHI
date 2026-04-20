# MK5 — 최종 정리

업데이트: 2026-04-20  
상태: **완료 (MK6로 이관)**

---

## 정체성

MK5는 **그래프 중심 인지 파이프라인**이다.

- LLM은 구조 판정/제안/언어화에 참여하는 **하위 모듈**
- 장기 상태와 판단 근거의 중심은 **그래프**
- 입력을 그래프에 적재 → 활성 그래프에서 사고 → 결론만 언어화

---

## 디렉토리 구조

```
MK5/
├── app/
│   ├── api.py                            # FastAPI 엔드포인트
│   ├── chat_pipeline.py                  # 전체 파이프라인 오케스트레이터
│   └── model_discovery.py                # Ollama 모델 목록 조회
├── core/
│   ├── activation/
│   │   ├── activation_engine.py          # ThoughtView 구성
│   │   └── pattern_detector.py           # 서브그래프 패턴 탐지
│   ├── cognition/
│   │   ├── input_segmenter.py            # 사용자 입력 → MeaningBlock 분해
│   │   ├── meaning_block.py              # MeaningBlock 엔티티
│   │   ├── hash_resolver.py              # address_hash 계산
│   │   └── direct_node_accessor.py
│   ├── entities/
│   │   ├── node.py
│   │   ├── edge.py
│   │   ├── thought_view.py               # 활성 부분 그래프
│   │   ├── conclusion.py                 # CoreConclusion (루프 내부 전용)
│   │   ├── conclusion_view.py            # ConclusionView (verbalization용)
│   │   ├── intent.py
│   │   ├── graph_event.py
│   │   ├── node_pointer.py
│   │   └── subgraph_pattern.py
│   ├── policies/
│   │   └── conflict_resolution_policy.py
│   ├── search/
│   │   ├── search_scope_gate.py          # 임베딩+코사인 기반 검색 필요 판정
│   │   ├── search_sidecar.py             # 검색 루프 조율
│   │   ├── question_slot_planner.py      # 검색 쿼리 슬롯 추출 (LLM)
│   │   ├── search_coverage_refiner.py    # 검색 결과 정제 (LLM)
│   │   ├── search_need_evaluator.py
│   │   └── search_query_planner.py
│   ├── thinking/
│   │   ├── thought_engine.py             # 메인 사고 엔진
│   │   ├── contradiction_detector.py     # 구조 충돌 감지
│   │   ├── trust_manager.py              # trust/pressure 갱신
│   │   ├── intent_manager.py             # intent snapshot 결정
│   │   ├── structure_revision_service.py # 구조 변경 실행
│   │   ├── conclusion_builder.py         # CoreConclusion 생성
│   │   ├── conclusion_view_builder.py    # ConclusionView 생성 (룰 기반)
│   │   ├── concept_differentiation_service.py  # 미구현 — MK6 이관
│   │   ├── revision_rule_analytics.py
│   │   └── revision_rule_tuner.py
│   ├── update/
│   │   ├── graph_ingest_service.py       # 그래프 적재
│   │   ├── graph_commit_service.py
│   │   ├── edge_update_service.py
│   │   ├── node_merge_service.py         # 얕은 병합 (shallow merge)
│   │   ├── pointer_rewrite_service.py
│   │   ├── revision_edge_service.py      # revision marker edge 생성
│   │   ├── model_edge_assertion_service.py  # LLM 기반 엣지 추론
│   │   ├── connect_type_promotion_service.py  # connect_type 승격 판정
│   │   ├── temporary_edge_service.py     # topic shift 시 임시 엣지 정리
│   │   └── source_trust_policy.py
│   └── verbalization/
│       ├── verbalizer.py
│       ├── ollama_verbalizer.py          # LLM 기반 응답 생성
│       ├── template_verbalizer.py
│       ├── action_layer_builder.py
│       └── meaning_preserver.py
├── tools/
│   ├── ollama_client.py                  # Ollama HTTP 클라이언트 (LLM + embed)
│   ├── revision_rule_report.py           # revision 분석 리포트
│   ├── revision_rule_apply_overrides.py  # override 자동 적용
│   ├── run_revision_rule_override_job.ps1
│   └── setup_revision_rule_scheduler.ps1
├── docs/
│   ├── architecture/                     # 컴포넌트별 상세 설계
│   ├── guid/                             # 마스터 문서
│   ├── handoff/                          # 세션 인계
│   ├── todo/                             # 작업 현황
│   └── troubleshooting/
├── config.py
├── run.py
└── requirements.txt
```

---

## 전체 파이프라인 — 실행 순서 및 방법

### Phase 1: User Ingest

`GraphIngestService`가 사용자 입력을 그래프에 기록한다.

1. `InputSegmenter`가 사용자 메시지를 **MeaningBlock** 단위로 분해
   - inquiry block(질문), relation block(관계), claim block(주장) 등으로 분류
2. `HashResolver`가 각 block의 `address_hash` 계산 — 동일 내용 재입력 시 중복 노드 방지
3. `address_hash` 기준으로 기존 노드 재사용 또는 신규 노드 생성
4. 노드 간 엣지/포인터 반영 (`edge_family`, `connect_type`, `relation_detail`)
5. `chat_message` 및 `graph_event(ingest)` 기록

### Phase 2: Activation — ThoughtView 구성

`ActivationEngine`이 현재 질의 중심의 활성 부분 그래프를 구성한다.

1. 현재 입력 기준 **seed block** 생성
2. `address_hash` 기반으로 seed 노드 탐색
3. seed 노드로부터 N-hop 로컬 노드/엣지/포인터 수집
4. `ThoughtView` 구성 — 이후 모든 사고 및 판정은 전체 그래프가 아닌 이 서브그래프에서만 수행
5. `PatternDetector`가 활성 그래프에서 서브그래프 패턴 탐지 후 ThoughtView에 추가

### Phase 3: Think→Search 루프 (최대 3회)

`_THINK_SEARCH_MAX_LOOPS = 3`

```python
for 최대 3회:
    ThoughtEngine.think()          # CoreConclusion 생성 (루프 내부 전용)
    SearchSidecar.run()            # CoreConclusion으로 검색 방향 결정
    if 검색 결과 없음:
        break                      # 현재 ThoughtResult가 최종
    Ingest(검색결과) → Re-Activation → 다음 회차
else:  # break 없이 3회 완주한 경우
    ThoughtEngine.think() 1회 추가  # 마지막 enriched ThoughtView 반영
```

#### ThoughtEngine 내부 순서 (매 회차)

**① ContradictionDetector — 구조 충돌 감지**

- 활성 ThoughtView 내 노드/엣지 간 구조 충돌 탐지
- 탐지 기준: conflict 엣지 존재, trust score 역전, 상반 주장 공존
- 충돌 신호를 생성해 TrustManager에 전달

**② TrustManager — 엣지 상태값 누적 갱신**

- `trust_score`, `support_count`, `conflict_count`, `contradiction_pressure` 갱신
- 누적 결과를 바탕으로 revision marker 엣지 생성/강화 여부 결정

**③ StructureRevisionService — 구조 변경 실행**

- `RevisionExecutionRule` 기반 게이트: `edge_family + connect_type + 상태값` 조합으로 분기
- 게이트 통과 조건: trust / contradiction_pressure / support_count / marker 누적량 기준
- marker 엣지 종류:
  - `conflict_assertion`
  - `revision_pending`
  - `deactivate_candidate`
  - `merge_candidate`
- 실행 종류: shallow merge / node deactivation
- runtime override 가능:
  - `REVISION_RULE_OVERRIDES_PATH` — override JSON 파일 경로
  - `REVISION_RULE_PROFILE` — `conservative | balanced | aggressive`
  - `REVISION_RULE_OVERRIDES_STRICT` — 로드 실패 시 에러 처리 여부

**④ IntentManager — intent snapshot 결정**

- 현재 그래프 상태를 보고 이번 사고의 우선순위를 결정하는 snapshot manager
- 판단 근거: contradiction 수, revision 수, inquiry/relation block 수, edge/pointer/pattern 수, 이전 어시스턴트 turn의 intent와 overlap
- 산출값:
  - `live_intent` / `snapshot_intent` / `previous_snapshot_intent`
  - `shifted` / `continuation` / `shift_reason`
  - `sufficiency_score` / `stop_threshold` / `should_stop`

**⑤ ConclusionBuilder — CoreConclusion 생성**

- **루프 내부 전용 중간 산물** — SearchSidecar가 검색 방향을 결정할 때만 사용
- Verbalization 계층에 직접 노출되지 않음

#### SearchSidecar 내부 순서 (매 회차)

**① SearchScopeGate — 외부 검색 필요 여부 판정 (임베딩+코사인)**

- `OllamaClient.embed()`로 `[query] + 활성노드 텍스트(max 30개)` 임베딩 일괄 요청
- `max(cosine(query_emb, node_emb)) ≥ SCOPE_GATE_SIMILARITY_THRESHOLD(기본 0.65)`
  - 임계치 이상 → 그래프로 충분 → 검색 불필요 → break
  - 임계치 미달 → 외부 근거 필요 → 검색 진행
- 활성 노드 0개 → 즉시 검색 필요
- fail-open: 임베딩 실패 시 `SearchScopeGateError` → `scope_gate_error` 노출 후 SlotPlanner 경로로 진행

**② QuestionSlotPlanner (LLM) — 검색 쿼리 슬롯 추출**

- 검색 필요 판정 시에만 실행
- CoreConclusion 기반으로 검색 쿼리 구조화: `entity`, `aspect`, `comparison_axes`

**③ 외부 검색 실행**

**④ SearchCoverageRefiner (LLM) — 검색 결과 정제**

- 검색 결과가 있을 때만 실행
- 결과 중 현재 ThoughtView와 관련성 높은 부분만 추출

**⑤ 정제된 결과 → GraphIngestService → ActivationEngine (Re-Activation)**

- 검색 결과를 그래프에 ingest 후 ThoughtView를 재구성, 다음 루프 회차로 진입

### Phase 4: ConclusionView 구성

`ConclusionViewBuilder`가 최종 ThoughtView와 ThoughtResult를 받아 룰 기반으로 결론 구조를 구성한다.

**선별 기준:**

- **노드**: `is_active=True` AND `trust_score ≥ 0.3` AND (topic_terms 키워드 매칭 OR 1-hop 이웃)
- **엣지**: 선별 노드 간 AND `connect_type ≠ 'conflict'` AND `trust_score ≥ 0.3`
- **정렬**: trust_score 내림차순 → logical_sequence

Verbalization 계층이 참조하는 **유일한 최종 결론 구조** (CoreConclusion 완전 대체).

### Phase 5: Verbalization

1. `ConclusionView`를 입력으로 `DerivedActionLayer` 구성
2. `OllamaVerbalizer` (LLM): 최종 사용자 응답 생성
   - `MeaningPreserver`가 ConclusionView의 핵심 의미 보존 보조

### Phase 6: Assistant Ingest

최종 응답도 다시 그래프에 적재된다.

- `source_trust_policy`가 어시스턴트 응답에 다른 신뢰도 정책 적용
- 이후 대화에서 어시스턴트 자신의 발화도 그래프 구조에 반영됨

---

## LLM 호출 구조

| 컴포넌트 | 종류 | 호출 조건 | 비고 |
|---|---|---|---|
| SearchScopeGate | 임베딩 (nomic-embed-text) | 매 루프 회차 | LLM 아님, 경량 |
| QuestionSlotPlanner | Ollama LLM | 검색 필요 판정 시만 | 루프당 최대 1회 |
| SearchCoverageRefiner | Ollama LLM | 검색 결과 있을 때만 | 루프당 최대 1회 |
| ModelEdgeAssertionService | Ollama LLM | 매 턴 | 턴당 1회 |
| OllamaVerbalizer | Ollama LLM | 매 턴 | 턴당 1회 |
| ModelFeedbackService | **제거됨** | — | LLM 절감 |

- **최소** (검색 불필요): **2회** — EdgeAssertion + Verbalizer
- **최대** (검색 3회 루프): **8회** — SlotPlanner×3 + CoverageRefiner×3 + EdgeAssertion + Verbalizer

---

## 그래프 모델

### Node

| 필드 | 설명 |
|---|---|
| `address_hash` | 중복 감지용 식별자 |
| `node_kind` | 노드 유형 |
| `raw_value` | 원본 텍스트 |
| `normalized_value` | 정규화 텍스트 |
| `trust_score` | 신뢰도 (0~1) |
| `stability_score` | 안정도 |
| `is_active` | 활성 여부 |
| `payload` | 부가 정보 |

### Edge — 3축 의미 표현

| 필드 | 값 | 설명 |
|---|---|---|
| `edge_family` | `concept \| relation` | 엣지의 의미 범주 |
| `connect_type` | `flow \| neutral \| opposite \| conflict` | 연결 방향성 |
| `relation_detail` | — | 보조 정보 (note/provenance/proposal/scope) |
| `support_count` | — | 누적 지지 횟수 |
| `conflict_count` | — | 누적 충돌 횟수 |
| `contradiction_pressure` | — | 모순 압력 누적값 |
| `trust_score` | — | 엣지 신뢰도 |

### Connect Type 확장 정책

모델이 허용 집합 밖 타입 제안 시:
1. 엣지는 `neutral`로 저장
2. `relation_detail.proposed_connect_type`에 후보 보존
3. `relation_detail.proposal_reason`으로 승격 근거 기록
4. `ConnectTypePromotionService`가 누적 점수(support_count × trust_score × 출처 가중치) 기반으로 승격 판정

---

## Trust & Revision 시스템

**원칙: 단발성 충돌로 즉시 구조 변경하지 않는다. 누적 기반 판정.**

1. `ContradictionDetector` → 구조 충돌 신호 생성
2. `TrustManager` → edge 상태값 누적 갱신 (trust/support/conflict/pressure)
3. marker edge 누적 (`conflict_assertion`, `revision_pending`, `deactivate_candidate`, `merge_candidate`)
4. `StructureRevisionService` → 누적 + `RevisionExecutionRule` 게이트로 실행 판정
   - 기준: `edge_family + connect_type + 상태값` 조합
   - 실행: shallow merge / node deactivation
5. graph event 기록

---

## 운영 설정

### 필수 전제조건

```bash
ollama pull nomic-embed-text
```

미설치 시 SearchScopeGate fail-open → SlotPlanner 경로로 폴백 (동작은 하나 LLM 비용 증가).

### 주요 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `EMBEDDING_MODEL_NAME` | `nomic-embed-text` | SearchScopeGate 임베딩 모델 |
| `EMBEDDING_TIMEOUT_SECONDS` | `10.0` | 임베딩 타임아웃 |
| `SCOPE_GATE_SIMILARITY_THRESHOLD` | `0.65` | 검색 필요 판정 임계치 (낮출수록 검색 자주) |
| `OLLAMA_TIMEOUT_SECONDS` | `360` | 루프 내 LLM 타임아웃 |
| `QUESTION_SLOT_PLANNER_TIMEOUT_SECONDS` | `90` | SlotPlanner 타임아웃 |
| `SEARCH_COVERAGE_REFINER_TIMEOUT_SECONDS` | `90` | CoverageRefiner 타임아웃 |
| `REVISION_RULE_OVERRIDES_PATH` | — | override JSON 파일 경로 |
| `REVISION_RULE_PROFILE` | `balanced` | revision 프로필 (`conservative \| balanced \| aggressive`) |
| `REVISION_RULE_OVERRIDES_STRICT` | `false` | override 로드 실패 시 에러 처리 여부 |

### 실행

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

### Revision Rule 운영

```bash
# 분석
python tools/revision_rule_report.py --db data/memory.db --suggest

# 적용
python tools/revision_rule_apply_overrides.py --db data/memory.db --preset balanced
```

기본 override 파일: `data/revision_rule_overrides.auto.json`  
ChatPipeline 시작 시 자동 로드.

### Windows 스케줄러

```powershell
# 1회 실행
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run_revision_rule_override_job.ps1 -ProjectRoot . -Preset balanced

# 스케줄 등록 (매일 03:30)
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup_revision_rule_scheduler.ps1 -ProjectRoot . -TaskName "MACHI-MK5-RevisionRuleOverride" -DailyTime "03:30" -Preset balanced
```

---

## MK6 이관 사항

### 공통부 추출 / 개념 분화 (미구현)

MK1 원설계의 "노드 = 체감된 개념(공통부 추출로 형성)" 철학이 MK5에서 미구현으로 남았다.

**MK5 한계:**
- 현재 노드는 "그래프가 체감한 개념"이 아니라 "텍스트를 저장한 버킷"에 가깝다
- `node.content = 텍스트 레이블` 구조에서는 부모 개념을 만들 때 LLM이 레이블을 붙이게 되고, 그 레이블이 의미를 정의해버리는 역전이 발생한다

**MK6 설계 방향:**
- 단어와 의미 분리: 의미는 그래프 구조(연결, 가중치, trust) 자체에 존재하고, 단어는 파생 표현
- 공통부 추출 흐름:
  1. ThoughtView(국부 활성 그래프) 내 유사 노드 쌍 탐지 (임베딩 코사인)
  2. 두 후보 각각의 국부 미니 그래프 구성 → 상호 임베딩 overlap 비율로 재확인
  3. 유사 확정 시 → 공통 의미 노드 생성 (텍스트 레이블 없이 구조로 존재)
  4. 차이는 기존 `proposed_connect_type` 승격 경로로 처리
  5. 기존 부모 재사용 없음 — 유사 부모들도 같은 과정으로 수렴
- 영향 범위: 노드 엔티티 구조, verbalization 계층, 인덱싱 전략 전면 재설계 필요

---

## 참고 문서

| 문서 | 경로 |
|---|---|
| 마스터 | `docs/guid/MK5_전체정리.md` |
| 아키텍처 상세 | `docs/architecture/*` |
| 검색/검증 전략 | `docs/guid/MK5_검색_및_검증_전략.md` |
| 핸드오프 | `docs/handoff/MK5_handoff.md` |
| 현재작업 | `docs/todo/현재작업.txt` |
