# MK5 handoff

기준 시점: 2026-04-16

## 프로젝트 정체
MK5는 입력을 바로 답변으로 보내는 시스템이 아니라, 입력을 하나의 관계 그래프에 축적하고, 그 그래프의 국소 활성 상태를 바탕으로 사고한 뒤 마지막에만 언어화하는 graph-first cognition 시스템이다.

핵심 원칙:
- user / assistant / search 입력을 같은 세계 그래프에 넣는다.
- 사고는 전체 그래프가 아니라 `ThoughtView` 위에서 일어난다.
- 본체는 설명용 conclusion이며, 행동 레이어는 얇은 파생 계층이다.
- fallback으로 얼버무리지 않고, 구조가 없으면 구조가 없다고 말하고 오류면 오류라고 말하는 쪽을 지향한다.
- 최근 대화 기억, 정체성, 주제 지속성도 프롬프트 트릭보다 그래프 구조 위에서 다루는 방향으로 가고 있다.

## 이번 스냅샷의 가장 큰 변화

### 1. Edge 구조가 바뀌었다
이제 Edge는 `edge_type` 중심이 아니라 다음 구조로 이동 중이다.

- `edge_family`
  - `concept`
  - `relation`
- `connect_type`
  - 초기값: `flow`, `neutral`, `opposite`
- `relation_detail`
  - `connect_semantics`
  - confidence / provenance / proposal 등 세부 의미

의미:
- 존재 계층은 `concept / flow`
- 이름/호칭/표상은 `concept / neutral`
- 일반 관계/상호작용은 `relation / flow` 또는 `relation / neutral`

주의:
- 같은 두 Node 사이에도 서로 다른 family/type/semantics를 가진 여러 Edge가 동시에 존재할 수 있다.
- `재용 -> Machi`의 개념적 연결과 관계적 연결은 동시에 공존 가능해야 한다.

### 2. schema와 repository 1차 교체가 들어갔다
변경 파일:
- `storage/schema.sql`
- `core/entities/edge.py`
- `storage/repositories/edge_repository.py`
- `storage/sqlite/edge_repository.py`

현재 상태:
- `edges` 테이블은 `edge_type` 대신 `edge_family`, `connect_type`를 쓴다.
- repository의 `find_active_relation()`은 이제
  - `edge_family`
  - `connect_type`
  - `connect_semantics`
  기준으로 찾는다.

중요:
- 기존 `memory.db`는 자동 마이그레이션되지 않는다.
- 오래된 DB 파일은 새 schema와 맞지 않을 수 있으므로 재생성 또는 별도 migration이 필요하다.

### 3. ingest / merge / contradiction / pattern 계층도 새 Edge 구조를 읽기 시작했다
반영된 핵심 파일:
- `core/update/graph_ingest_service.py`
- `core/update/node_merge_service.py`
- `core/thinking/contradiction_detector.py`
- `core/activation/pattern_detector.py`

현재 의미:
- same-sentence co-occurrence는 이제 `relation / neutral / same_sentence_co_occurrence`
- merge 시 duplicate 판단도 family/type/semantics 기준으로 움직인다
- contradiction/debug는 `edge_label` 기반으로 읽기 시작했다

### 4. identity anchor 1차 도입
이번 스냅샷에서 가장 중요한 추가 개념이다.

`graph_ingest_service.py`가 세션/role 기준으로 다음 anchor node를 만들 수 있다.
- `user_self`
- `assistant_self`
- `search_source_self`

이 anchor들은 이번 turn에서 만들어진 의미 블록 노드와 `relation / flow` edge로 연결된다.

현재 semantics:
- `user_authored_node`
- `assistant_authored_node`
- `search_evidence_node`

이 작업은 문자열 휴리스틱이 아니라
- `session_id`
- `role`
- `source_type`
기반으로만 이루어진다.

### 5. activation이 identity 축을 보기 시작했다
`activation_engine.py`는 이제 세션 identity anchor를 local view에 포함한다.

현재 metadata:
- `identity_node_ids`
- `identity_terms`

즉 아직은 정교한 identity reasoning 전 단계지만, 그래프가 최소한 "이 세션의 user / assistant 축"을 활성화할 수 있는 상태가 되었다.

## 현재 구현된 큰 줄기
- SQLite schema / repository / unit-of-work
- `GraphIngestService`
- `ActivationEngine`
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- revision 단계 shallow merge
- `NodeMergeService` / `PointerRewriteService`
- `IntentManager`
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

## 이번 스냅샷까지 검증한 것

### 코드 수준
- `py_compile`로 핵심 변경 파일 문법/임포트 확인

### 워크스페이스 내부 smoke check
임시 DB를 워크스페이스 안에 생성해서 다음을 확인했다.
- 새 edge schema 저장/조회
- merge 후 semantics 기준 edge 병합
- identity anchor 생성 및 activation 반영

주의:
- 기존 스크립트형 테스트 일부는 Windows temp directory 권한 문제로 그대로 실행되지 않았다.
- 따라서 이번 검증은 workspace-local DB smoke check 중심이었다.

## 지금 남아 있는 가장 중요한 리스크

### 1. 기존 DB 마이그레이션 부재
가장 큰 실무 리스크다.

현재 `schema.sql`은 완전 교체 방향으로 바뀌었지만:
- 기존 DB를 alter 하는 migration은 없다.
- `initialize_schema()`는 `CREATE TABLE IF NOT EXISTS`만 하므로 기존 컬럼을 자동 교체하지 못한다.

즉 새 코드와 오래된 `memory.db`를 그대로 같이 쓰면 깨질 가능성이 높다.

### 2. `edge_type` 잔존 개념이 아직 일부 설명 계층에 남아 있다
현재는 `edge_label`로 걷어내는 중이다.

남은 포인트:
- 일부 conclusion/debug/UI 용어
- 일부 테스트 명칭
- 오래된 문서 표현

### 3. identity anchor는 들어갔지만 identity refinement는 아직 없다
지금은:
- `user_self`
- `assistant_self`
anchor만 들어간 상태다.

아직 안 된 것:
- `지성체 -> 사람 -> 나`
- `지성체 -> AI -> Machi`
- `concept / neutral` 이름/호칭 군집
- `Jay`, `재용`, `신재용` 같은 표상 클러스터

즉 현재는 identity reasoning의 기반만 들어갔고, 존재 계층과 naming cluster는 아직 시작 전이다.

### 4. contradiction / revision 규칙은 새 Edge 구조를 완전히 다 소화하지 못한다
현재는 일부 semantics만 새 구조로 읽는다.

향후 필요:
- `edge_family / connect_type / connect_semantics` 기준의 revision 규칙 고도화
- `opposite` 계열 연결 처리
- concept/relation을 다르게 다루는 contradiction policy

### 5. search / error contract 쪽 과제는 여전히 남아 있다
이번 스냅샷의 중심은 그래프 구조 변경이었기 때문에, 아래 과제는 아직 열려 있다.

- search fail-open 잔여 정책 정리
- provider failure / no-result / transport error 분리
- groundedness 억제 강화
- search fixture / integration test 정리

## 다음 작업 추천

### P0
1. 기존 DB migration 또는 재생성 전략 결정
2. `edge_type` 잔존 개념 정리 마무리
3. identity refinement 시작
   - `concept / flow`
   - `concept / neutral`
   기반으로 존재 계층과 이름 표상 클러스터 생성

### P1
4. contradiction / revision 규칙을 새 Edge 구조 기준으로 재정리
5. activation / thinking에서 `identity_context`를 더 직접적으로 읽게 만들기
6. memory probe / naming continuity를 identity graph 기반으로 연결

### P2
7. as-of 조회 기반 설계 구체화
8. search/error contract 미완성 부분 복구

## 지금 바로 보면 좋은 파일
- `storage/schema.sql`
- `core/entities/edge.py`
- `storage/sqlite/edge_repository.py`
- `core/update/graph_ingest_service.py`
- `core/activation/activation_engine.py`
- `core/thinking/contradiction_detector.py`
- `docs/개념업데이트_정체성_시간성_그래프.md`
- `docs/설계초안_정체성엣지_시점역추적_파이프라인.md`
- `docs/설계초안_schema_edge_repository_마이그레이션.md`

## 커밋 단위 제안
이번 변경은 실제로는 두 커밋으로 나누면 가장 자연스럽다.

1. Edge 구조 완전 교체
- schema
- edge entity
- repository
- ingest/merge/pattern/contradiction 적응

2. identity anchor 1차 도입
- graph ingest anchor 생성
- activation identity metadata 반영
- 관련 테스트/문서

하지만 하나로 묶어도 된다면, "graph edge model 교체 + identity anchor 도입"으로 볼 수 있다.
