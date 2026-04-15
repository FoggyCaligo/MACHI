# MK5 handoff

## 프로젝트 정체
MK5는 MK4의 profile 중심 기억 구조를 넘어서,
**하나의 세계 그래프 + 국부 활성화 + intent snapshot + 설명형 conclusion** 구조로 가는 초기형 인지 시스템이다.

핵심은:
- 모든 입력을 chat 흐름으로 본다.
- 원문은 provenance로 남긴다.
- 그래프에는 재사용 가능한 의미블록을 저장한다.
- 사고는 전체 그래프가 아니라 `ThoughtView` 위에서 일어난다.
- 본체는 설명형 `CoreConclusion`이다.
- 행동형은 `DerivedActionLayer`로 얇게 파생된다.
- user / assistant / search / file는 같은 세계 그래프 안에 들어가되 trust는 차등적이다.

---

## 현재 구현 상태
### 이미 연결된 것
- SQLite schema / repository / UoW
- `GraphIngestService`
- `ActivationEngine`
- `PatternDetector` / `ConflictResolutionPolicy`
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- **revision 단계 shallow merge**
- `NodeMergeService` / `PointerRewriteService`
- **`IntentManager` 기반 intent snapshot 결정**
- `ConclusionBuilder`
- `DerivedActionLayer`
- `TemplateVerbalizer`는 사용자 응답 fallback 금지 상태이며, 내부 설명 전용이다.
- `OllamaVerbalizer`는 prompts/ 아래 프롬프트 파일을 로드해 사용자 질문 중심으로 답하도록 바뀌었다.
- `SearchSidecar`
- assistant 답변 재-ingest
- end-to-end chat pipeline

### 아직 안 된 것
- trusted_search 기반 검색 전환
- `tools/ollama_client.py` 실구현
- `graph_commit_service.py` 실구현
- `edge_update_service.py` 실구현
- meaning block / contradiction / revision 고도화
- Flask 실서버 확인
- requirements 정리

---

## 현재 가장 중요한 확정 정책
### 1. 세계 그래프는 하나다
별도 profile/project/chat 층을 두지 않는다.
모든 입력은 같은 그래프에 들어간다.
다만 trust는 source-aware 하게 시작한다.

### 2. 설명형 conclusion이 본체다
행동형은 설명형에서 파생된다.
`activated_concepts`와 `key_relations`는 그래프 참조다.

### 3. 기본은 구조 보존이다
반복 충돌 전에는 기존 구조를 바로 부수지 않는다.

### 4. merge 정책은 A안이다
- **revision 단계에서만 merge**
- ingest 직후 자동 merge 안 함
- **조금 얕은 누적량**에서 candidate review 시작
- 실제 merge는 duplicate-like node에 한정

### 5. intent는 문자열 키워드로 정하지 않는다
현재 intent snapshot은
- contradiction / revision
- seed / node / edge / pointer / pattern 수
- recent session continuity
를 보고 결정한다.

---

## 다음 우선 작업
1. trusted_search 기반 검색 레이어로 전환
2. `tools/ollama_client.py` 실구현
3. `graph_commit_service.py` / `edge_update_service.py` 실구현
4. search corroboration
5. meaning block / contradiction / revision 고도화

---

## 실행 / 테스트
### Windows
```bash
py -m venv .venv
.venv\Scripts\activate
pip install flask
python run.py
```

### 테스트
```bash
python tests/unit/test_sqlite_repository_smoke.py
python tests/unit/test_intent_manager.py
python tests/integration/test_chat_graph_pipeline.py
python tests/integration/test_activation_engine_pipeline.py
python tests/integration/test_thinking_revision_pipeline.py
python tests/integration/test_revision_driven_node_merge.py
python tests/integration/test_end_to_end_chat_pipeline.py
python tests/integration/test_intent_snapshot_pipeline.py
```

---

## 새 채팅에서 한 줄 요약
“MK5는 이제 user/search/assistant 입력을 같은 세계 그래프에 source-aware trust로 넣고, revision 단계 shallow merge와 intent snapshot까지 포함한 최소 end-to-end 루프가 연결된 상태다.”
