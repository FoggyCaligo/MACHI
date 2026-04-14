# MK5 handoff

## 이 문서의 목적
새 채팅으로 넘어갈 때, 지금까지의 상태와 철학, 작업 규칙, 다음 우선 작업을 잃지 않기 위한 handoff 문서다.

---

## 프로젝트 정체
MK5는 기존 MK4의 profile/candidate/summary 중심 저장 구조를 버리고,
**의미블록 기반 그래프 + 국부 활성화 + 설명형 conclusion + 얇은 행동형 레이어** 구조로 넘어간 실험판이다.

핵심은:
- 모든 입력을 chat 흐름으로 본다.
- 원문은 provenance로 저장한다.
- 영구 그래프에는 재사용 가능한 의미블록을 저장한다.
- 사고는 전체 그래프가 아니라 `ThoughtView`라는 국부 활성화 그래프 위에서 일어난다.
- 결론의 본체는 설명형 `CoreConclusion`이다.
- 행동형은 `DerivedActionLayer`로 파생된다.
- 사용자, 모델, 검색 결과는 모두 같은 세계 그래프에 들어가되, source-aware trust 정책으로 차등화된다.

---

## 현재 완료 상태

### 저장 / DB
- `nodes / edges / graph_events / node_pointers / chat_messages` 스키마 있음
- SQLite repository 구현 있음
- `SqliteUnitOfWork` 있음

### ingest
- `GraphIngestService` 있음
- 의미블록 추출 -> hash 조회 -> node 재사용/생성 -> edge/pointer/event 기록까지 됨
- source_type / claim_domain 기반 trust 반영됨

### activation
- `ActivationEngine` 있음
- seed block / seed node / local nodes / local edges / pointers를 모아 `ThoughtView` 생성

### thinking
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- `ThoughtEngine`

즉, 충돌 감지 / trust 하락 / revision 검토 흐름이 있음

### conclusion / verbalization
- `CoreConclusion` dataclass 있음
- `ConclusionBuilder` 있음
- `DerivedActionLayer` 있음
- `TemplateVerbalizer` 있음
- `OllamaVerbalizer` 있음
- 선택된 모델이 실제 verbalization에 참여 가능

### search / assistant ingest
- `SearchSidecar` 있음
- explanation 계열 질문에는 검색 결과를 가져와 낮은 trust로 같은 세계 그래프에 넣을 수 있음
- assistant 최종 답변도 낮은 trust로 같은 세계 그래프에 반영됨

### app
- `app/chat_pipeline.py` 기준으로 end-to-end 동작
- `app/api.py`에 최소 Flask 라우트 셸 있음
- `app/static/chat.*` 기본 UI 있음

### tests
- smoke / ingest / activation / thinking / end-to-end integration test 있음
- 로컬 컨테이너 기준 통과 확인함

---

## 가장 중요한 철학

### 1. 설명형 conclusion이 본체
행동형은 설명형에서 파생 가능하지만, 행동형만으로는 원래 사고 구조를 복원하기 어렵다.
따라서 본체는 항상 설명형이다.

### 2. activated_concepts / key_relations는 참조
- `activated_concepts` = node id 목록
- `key_relations` = edge id 목록
즉 conclusion은 그래프 본체를 복제하지 않고 참조한다.

### 3. 기본은 구조 보존
새 구조가 기존 구조를 바로 부수지 않는다.
다만 반복 반례가 누적되면 trust를 낮추고, 임계점 아래로 내려가면 revision candidate로 보고 구조를 교체할 수 있다.

### 4. 세계 그래프는 하나다
사용자 발화, 모델 발화, 검색 결과를 별도 층으로 떼지 않는다.
하나의 세계 그래프 안에 모두 넣되, source_type과 claim_domain에 따라 trust를 차등 부여한다.

### 5. 존재와 확실성은 다르다
정보가 그래프에 들어온다고 해서 곧바로 안정된 세계지식이 되는 것은 아니다.
- 낮은 trust로 들어갈 수는 있다.
- 반복성과 교차 일치로 강화된다.
- 충돌과 반례로 약해진다.

### 6. 언어화는 사고가 아니다
현재 template verbalizer와 OLLAMA verbalizer는 conclusion + action layer를 말로 바꾸는 역할만 한다.

---

## 작업 규칙
- 기준본은 항상 **현재 로컬 작업본**이다.
- 사용자가 zip을 주는 건 **sync용**이다.
- 수정 결과는 zip 기준 새 분기로 만들지 않는다.
- 수정 사항을 전달할 땐 **파일경로 - 다운로드 링크** 형식으로 준다.
- 정책/철학 분기점이 생기면 먼저 멈추고 사용자에게 물어본다.
- 구현 문제와 철학 문제를 섞지 않는다. 단순 실행 결함은 바로 고친다.

---

## 현재 안 된 것
- Flask 실서버 기동 검증은 이 작업 환경에서 못 했음
- `requirements.txt` 없음
- `chat.js` 최신본이 네 로컬에 실제 반영됐는지/브라우저 캐시가 남았는지 확인 필요
- search corroboration 정책 없음
- source-aware trust policy는 아직 시작점 수준
- meaning block / contradiction / revision 규칙 정교화 필요

---

## 다음 우선 작업
1. `requirements.txt` 추가
2. `chat.js` 최신본 실제 반영 및 debug UI 최종 정리
3. search corroboration 정책 추가
4. source_type × claim_domain 신뢰도 정책 세밀화
5. meaning block / contradiction / revision 규칙 정교화

---

## 실행 명령어
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
python tests/integration/test_chat_graph_pipeline.py
python tests/integration/test_activation_engine_pipeline.py
python tests/integration/test_thinking_revision_pipeline.py
python tests/integration/test_end_to_end_chat_pipeline.py
```

---

## 새 채팅에서 바로 이어갈 때 한 줄 요약
“MK5는 이제 user / search / assistant 입력을 source-aware trust로 같은 세계 그래프에 반영하는 end-to-end 최소 루프까지 연결된 상태고, 다음 우선 작업은 requirements 정리와 search corroboration, trust 정책 세밀화다.”
