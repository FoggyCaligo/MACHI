# MK5

## 한 문장 정의
MK5는 **입력을 의미 단위로 분해하고, 하나의 세계 그래프에 누적하며, 그 그래프의 국부 활성화 위에서 사고를 전개한 뒤, 마지막에만 언어화하는 인지형 대화 시스템**이다.

즉 목표는 “더 좋은 답변 생성기”가 아니라,
**인지 → 활성화 → 의도 스냅샷 → 구조 점검 / revision → 설명형 결론 → 얇은 행동형 레이어 → 언어화**를 분리하는 것이다.

---

## 프로젝트의 방향
MK5는 MK4의 `profile / candidate / confirmed` 중심 구조를 그대로 확장하는 프로젝트가 아니다.
중심축을 **사용자 프로필 저장**에서 **세계 그래프 기반 판단**으로 옮긴다.

핵심 방향은 다음과 같다.

1. **세계 그래프는 하나다.**
   - user / assistant / search / file 입력을 별도 층으로 떼지 않는다.
   - 대신 같은 그래프 안에 넣되, `source_type × claim_domain`에 따라 trust를 다르게 둔다.

2. **노드는 문장이 아니라 재사용 가능한 의미 단위다.**
   - 원문 전체는 provenance로 남고,
   - 그래프에는 의미블록이 재사용 가능한 형태로 들어간다.

3. **설명형 conclusion이 본체다.**
   - 행동형 지시는 설명형 conclusion에서 파생된다.
   - 본체는 항상 `CoreConclusion`이며, `activated_concepts` / `key_relations`는 node / edge 참조다.

4. **기본은 구조 보존이다.**
   - 새 입력이 들어와도 기존 연결을 즉시 부수지 않는다.
   - 반복 충돌과 trust 하락이 누적될 때만 revision 단계에서 구조 교체를 검토한다.

5. **언어화는 사고가 아니다.**
   - verbalizer는 이미 만들어진 결론을 한국어로 바꾸는 역할만 맡는다.

---

## 현재 구현 상태

### 현재 이미 연결된 것
- SQLite 스키마 / repository / unit of work
- `GraphIngestService`
- 의미블록 분해 후 node 재사용/생성
- source-aware trust policy
- partial reuse pointer 생성
- `ActivationEngine` → `ThoughtView`
- `PatternDetector` / `ConflictResolutionPolicy`
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- **revision 단계 shallow node merge**
- `NodeMergeService` / `PointerRewriteService`
- **`IntentManager` 기반 intent snapshot 결정**
- 설명형 `CoreConclusion`
- `DerivedActionLayer`
- `TemplateVerbalizer` (사용자 응답 fallback 금지, 내부 설명 전용)
- `OllamaVerbalizer` (프롬프트는 prompts/ 에서 로드)
- search sidecar
- assistant 답변의 그래프 반영
- chat end-to-end pipeline
- 최소 Flask API 셸 / chat UI
- integration tests

### 아직 안 된 것
- `tools/ollama_client.py` 실구현
- trusted_search 기반 검색 레이어로 전환
- search corroboration 고도화
- `graph_commit_service.py` 실구현
- `edge_update_service.py` 실구현
- meaning block 정교화
- contradiction / revision 규칙 고도화
- Flask 실서버 기동 검증
- requirements 정리

---

## 현재 사고 흐름
1. 사용자 입력 수신
2. `GraphIngestService`가 user source로 chat_message / graph_event / node / edge / pointer 기록
3. `ActivationEngine`이 현재 입력 기준 `ThoughtView`를 생성
4. `PatternDetector`가 local graph 패턴을 감지
5. `ThoughtEngine`이 아래를 순서대로 수행
   - contradiction 감지
   - trust 하락 및 revision candidate 표기
   - revision 단계 검토
   - 필요 시 shallow duplicate merge 또는 edge deactivation
   - **`IntentManager`가 현재 그래프 상태와 최근 session continuity를 바탕으로 intent snapshot 결정**
6. `ConclusionBuilder`가 설명형 `CoreConclusion` 생성
7. 필요 시 `SearchSidecar`가 외부 검색 결과를 가져와 낮은 trust로 그래프에 반영
8. 다시 activation / thinking
9. `DerivedActionLayer` 생성
10. verbalizer가 최종 사용자 응답 생성
11. assistant 답변도 낮은 trust로 같은 세계 그래프에 반영

---

## Intent snapshot 정책
현재 `IntentManager`는 완전한 의도 함수 엔진은 아니다.
대신, 지금 사고 사이클에서 무엇을 우선할지를 고르는 **상태 전이기**로 동작한다.

현재 선택 가능한 snapshot intent:
- `structure_review`
- `memory_probe`
- `open_information_request`
- `relation_synthesis_request`
- `graph_grounded_reasoning`

판단 근거:
- contradiction 수
- trust update / revision 수
- seed / node / edge / pointer 수
- pattern 존재 여부
- 직전 assistant turn에 저장된 이전 intent snapshot과의 overlap

의미:
- 의도는 문자열 키워드가 아니라 **현재 그래프 상태 + 최근 사고 연속성**으로 결정된다.
- assistant 답변 metadata에 `intent_snapshot`이 저장되며, 다음 turn에서 continuity / shift 판단에 사용된다.

---

## Revision 단계 merge 정책
현재 merge는 **A안**으로 고정되어 있다.

- ingest 직후 바로 merge하지 않는다.
- revision candidate가 된 edge를 `StructureRevisionService`가 review할 때만 merge를 검토한다.
- 누적량은 보수적으로 높게 잡지 않고, **조금 얕은 임계치**를 사용한다.

현재 방향:
- trigger는 얕게
- merge 허용 조건은 보수적으로

즉, 지금은 “구조가 조금만 흔들려도 바로 다 합친다”가 아니라,
**revision review 단계에서 duplicate-like 노드만 먼저 정리하는 초기형 merge**다.

---

## 신뢰도 정책 개요
### source_type 예시
- `user`
- `assistant`
- `search`
- `file`

### claim_domain 예시
- `user_state_or_preference`
- `general_claim`
- `graph_interpretation`
- `generated_answer`
- `world_fact`

### 기본 원칙
- 사용자 자기 상태/선호 진술은 비교적 높은 trust에서 시작
- 검색 결과와 모델 발화는 더 낮은 trust에서 시작
- support와 교차 일치가 누적되면 trust 상승
- conflict와 반례가 누적되면 trust 하락 및 revision 후보화

---

## 실행
### Windows
```bash
py -m venv .venv
.venv\Scripts\activate
pip install flask
python run.py
```

브라우저:
```text
http://127.0.0.1:5000
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

## 다음 우선 작업
1. `tools/ollama_client.py` 실구현
2. search를 위키피디아 전용이 아니라 trusted_search 기반으로 전환
3. search corroboration 정책 추가
4. `graph_commit_service.py` / `edge_update_service.py` 실구현
5. meaning block / contradiction / revision 규칙 정교화
6. requirements 정리 및 Flask 실서버 확인

---

## 주의
- zip 업로드는 sync용일 뿐, 기준본은 항상 현재 로컬 작업본이다.
- 수정 사항은 파일 단위로 순차 패치한다.
- 정책/철학 분기점이 나오면 먼저 사용자에게 묻는다.
