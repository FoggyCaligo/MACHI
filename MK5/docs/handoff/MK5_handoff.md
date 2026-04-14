# MK5 handoff

## 이 문서의 목적
새 채팅으로 넘어갈 때, 지금까지의 상태와 철학, 작업 규칙, 다음 우선 작업을 잃지 않기 위한 handoff 문서다.

---

## 프로젝트 정체
MK5는 기존 MK4의 profile/candidate/summary 중심 저장 구조를 버리고,
**의미블록 기반 그래프 + 국부 활성화 + 설명형 conclusion** 구조로 넘어간 실험판이다.

핵심은:
- 모든 입력을 chat 흐름으로 본다.
- 원문은 provenance로 저장한다.
- 영구 그래프에는 재사용 가능한 의미블록을 저장한다.
- 사고는 전체 그래프가 아니라 `ThoughtView`라는 국부 활성화 그래프 위에서 일어난다.
- 결론의 본체는 설명형 `CoreConclusion`이다.
- 행동형은 그 위에서 파생된다.

---

## 현재 완료 상태

### 저장 / DB
- `nodes / edges / graph_events / node_pointers / chat_messages` 스키마 있음
- SQLite repository 구현 있음
- `SqliteUnitOfWork` 있음

### ingest
- `GraphIngestService` 있음
- 의미블록 추출 -> hash 조회 -> node 재사용/생성 -> edge/pointer/event 기록까지 됨

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
- `TemplateVerbalizer` 있음
- 설명형 conclusion -> 자연어 응답까지 연결됨

### app
- `app/chat_pipeline.py` 기준으로 end-to-end 동작
- `app/api.py`에 최소 Flask 라우트 셸 있음
- `app/static/chat.*` 기본 UI 있음

### tests
- smoke / ingest / activation / thinking / end-to-end integration test 있음

---

## 현재 안 된 것
- Flask 실서버 기동 검증은 이 작업 환경에서 못 했음 (Flask 미설치)
- `requirements.txt` 없음
- debug 정보가 아직 UI 패널이 아니라 시스템 메시지 텍스트로 출력됨
- 행동형 derived plan 없음
- local LLM verbalizer 없음
- meaning block 추출은 아직 단순 시작점 수준
- revision 고도화 부족
- project 셀렉터/UI 잔재가 남아 있으나 철학상은 chat 단일 흐름이 맞음

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

### 4. 문장은 영구 노드가 아니다
- 원문/문장 = provenance, 사건 기록
- 영구 그래프 = 재사용 가능한 의미블록

### 5. 언어화는 사고가 아니다
현재 template verbalizer는 conclusion을 말로 바꾸는 역할만 한다.
나중에 작은 로컬 LLM을 붙여도, 역할은 언어화 전용이어야 한다.

---

## 작업 규칙
- 기준본은 항상 **현재 로컬 작업본**이다.
- 사용자가 zip을 주는 건 **sync용**이다.
- 수정 결과는 zip 기준 새 분기로 만들지 않는다.
- 수정 사항을 전달할 땐 **파일경로 - 다운로드 링크** 형식으로 준다.
- 정책/철학 분기점이 생기면 먼저 멈추고 사용자에게 물어본다.
- 구현 문제와 철학 문제를 섞지 않는다. 단순 실행 결함은 바로 고친다.

---

## 다음 우선 작업

### 우선순위 1
- debug 정보를 UI에서 분리된 패널/토글 형태로 보이게 만들기
- 현재는 시스템 메시지 텍스트로 흘러서 가독성이 떨어진다.

### 우선순위 2
- `requirements.txt` 추가
- 실행 절차 문서화 강화

### 우선순위 3
- 행동형 derived plan 추가
- 단, 설명형 core conclusion을 본체로 유지

### 우선순위 4
- local LLM verbalizer 추가
- template verbalizer와 선택 가능하게 구성

### 우선순위 5
- meaning block / contradiction / revision 규칙 정교화

---

## 실행 명령어
### Windows
```bash
py -m venv .venv
.venv\Scriptsctivate
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
“MK5는 의미블록 기반 그래프 + 국부 활성화 + 설명형 core conclusion 구조로 이미 end-to-end 최소 루프가 연결되어 있고, 다음 우선 작업은 debug UI 패널화다.”
