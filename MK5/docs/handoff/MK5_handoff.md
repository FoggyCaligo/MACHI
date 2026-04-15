# MK5 handoff

기준 시점: 2026-04-15

## 프로젝트 정체
MK5는 MK4의 profile 중심 기억 구조를 그대로 확장하는 프로젝트가 아니라, 하나의 관계 그래프 위에서 입력을 축적하고 그 그래프의 국소 활성 상태를 바탕으로 사고한 뒤 마지막에만 언어화하는 graph-first cognition 시스템이다.

핵심 원칙:
- user / assistant / search / file 입력을 같은 그래프에 넣는다.
- 문장보다 "사실화 가능한 block"을 더 중요한 단위로 본다.
- 사고는 전체 그래프가 아니라 `ThoughtView` 위에서 일어난다.
- 본체는 설명용 conclusion이며, 행동성 지시는 그 conclusion에서 파생된다.
- Machi는 fallback으로 얼버무리는 시스템이 아니라, 구조가 없으면 구조가 없다고 말하고 오류면 오류라고 말하는 시스템을 지향한다.

## 현재 구현된 것
- SQLite schema / repository / unit-of-work
- `GraphIngestService`
- `ActivationEngine`
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- revision 단계 shallow merge
- `NodeMergeService` / `PointerRewriteService`
- `IntentManager` 기반 intent snapshot
- `ConclusionBuilder`
- `DerivedActionLayer`
- `TemplateVerbalizer`
  - 사용자 응답 fallback 제거됨
- `OllamaVerbalizer`
- `SearchSidecar`
- `QuestionSlotPlanner`
- `SearchNeedEvaluator`
- `SearchQueryPlanner`
- assistant reply 재ingest
- Flask chat API / UI

## 이번 스냅샷에서 이미 반영된 변화
- 문자열 휴리스틱 기반 fallback들이 여러 군데에서 제거되었다.
- `ConclusionBuilder`의 intent fallback이 제거되었다.
- `TemplateVerbalizer`의 사용자 응답 fallback이 제거되었다.
- search debug UI와 backend payload shape mismatch가 수정되었다.
- 검색이 필요한데 모델이 선택되지 않은 경우, 조용히 실패하지 않고 사용자 오류로 반환된다.
- `QuestionSlotPlanner`가 `search_aspects`와 `comparison_axes`를 분리하도록 확장되었다.
- search 결과가 0건이면 `no_evidence_found`가 verbalization까지 전달된다.
- search evidence ingest 뒤 groundedness를 한 번 더 평가하도록 보강되었다.

## 아직 남아 있는 실제 리스크

### 1. search 오류 정책이 완전히 일관적이지 않다
- `QuestionSlotPlanner` 실패 중 일부는 아직 `slot_planner_failed_needs_grounding`으로 fail-open된다.
- Machi 철학상 장기적으로는 이것도 담백한 오류 surface 쪽이 더 일관적이다.

### 2. provider failure와 no-result가 충분히 분리되지 않았다
- 현재 backend는 Wikipedia 중심이며, 실패와 "결과 없음"이 구조적으로 충분히 분리되어 있지 않다.
- `provider_errors` 시각화와 전파도 더 보강이 필요하다.

### 3. groundedness 억제가 아직 약하다
- `grounded_terms`, `missing_terms`, `missing_aspects`, `no_evidence_found`는 이제 전달되지만, 실제 응답 단정 수준을 충분히 강하게 통제하는지는 더 검증이 필요하다.

### 4. search 쪽 테스트와 구현 상태가 조금 어긋난다
- 일부 integration fixture는 예전 `SearchEvidence` 필드 형태를 아직 가정하고 있다.
- 테스트 체계가 현재 계약을 완전히 커버한다고 보기는 어렵다.

### 5. placeholder 서비스가 남아 있다
- `core/update/graph_commit_service.py`
- `core/update/edge_update_service.py`
- `core/verbalization/meaning_preserver.py`
- `tools/response_runner.py`
- `app/orchestrator.py`
- `app/routes/chat.py`
- `core/verbalization/llm_verbalizer.py`

## 가장 중요한 현재 판단
지금 MK5에서 가장 중요한 것은 기능을 넓히는 것이 아니라, 이미 들어온 graph-first 루프를 철학과 계약 측면에서 더 정직하고 안정적으로 만드는 것이다.

우선순위는 다음이 맞다.
1. search / error contract 정리
2. groundedness 강화
3. search backend 확장
4. graph semantics 강화
5. placeholder 서비스 실구현

## 다음 작업 추천
1. `SearchSidecar`의 fail-open 잔여 정책 정리
2. provider failure / no-result / transport error 구분
3. groundedness 억제 강화
4. search 관련 테스트 정리
5. trusted-search backend 확장
6. `graph_commit_service.py` / `edge_update_service.py` 설계 구체화

## 확인 포인트
- 검색이 필요한 질문에서 model 미선택 시 HTTP 400 사용자 오류가 올라오는지
- chat UI search debug가 `requested_slots`, `covered_slots`, `missing_slots`, `issued_slot_queries`, `comparison_axes`, `no_evidence_found`를 정상 렌더링하는지
- integration 테스트 fixture가 현재 `SearchEvidence` 계약과 맞는지
- verbalizer가 search gap이나 `result_count=0` 상태를 자연스럽게 메우는 방향으로 과장하지 않는지

## 실행 메모
Windows 예시:
```bash
py -m venv .venv
.venv\Scripts\activate
pip install flask
python run.py
```

테스트:
```bash
python -m py_compile MK5/app/chat_pipeline.py MK5/app/api.py MK5/tests/unit/test_chat_pipeline_user_errors.py
```

참고:
- 현재 작업 환경에서는 `pytest`가 설치되어 있지 않아 전체 테스트 실행 가능 여부를 별도로 확인해야 한다.
