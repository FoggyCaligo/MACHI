# MK5

## 개요
MK5는 기존의 “프로필 문장 저장 + 프롬프트 주입” 중심 구조에서 벗어나,
**입력을 의미 단위로 분해하고, 그래프 형태로 저장하며, 그 그래프의 국부 활성화 위에서 사고를 전개한 뒤, 마지막에만 언어로 표현하는 인지형 대화 시스템**을 목표로 한다.

즉 MK5의 핵심은 “더 좋은 답변 생성기”가 아니라,
**인지 → 사고 → 결론 → 언어화**를 분리한 구조를 실제로 구현하는 데 있다.

---

## 이 프로젝트가 장기적으로 갖는 의미
이 프로젝트는 단순히 기존 LLM 위에 메모리를 덧씌우는 실험이 아니다.
장기적으로는 다음 문제의식을 다룬다.

1. **정보를 받는 것과 이해하는 것을 분리한다.**
   - 기존 언어모델은 입력을 받아 바로 다음 토큰 생성으로 연결한다.
   - MK5는 입력을 그대로 답변으로 연결하지 않고, 먼저 의미블록과 관계로 해석한다.

2. **지식을 문장 모음이 아니라 구조로 취급한다.**
   - 노드는 문장 자체가 아니라, 반복 입력을 거치며 체감되고 안정화된 개념이다.
   - 엣지는 단순 연결이 아니라 관계와 차이와 조건을 담는다.

3. **사고를 블랙박스가 아니라 구조적 과정으로 다룬다.**
   - 어떤 개념이 활성화되었는지
   - 어떤 관계가 근거가 되었는지
   - 어떤 충돌이 감지되었는지
   - 왜 trust가 하락했는지
   가 남아야 한다.

4. **설명 가능한 구조를 본체로 둔다.**
   - 행동형 지시는 설명형 conclusion으로부터 파생 가능하다.
   - 반대로, 설명 없는 행동형 결론만으로는 원래 사고 구조를 복원하기 어렵다.
   - 그래서 MK5의 본체는 설명형이고, 행동형은 파생 출력이다.

5. **이론상 범용 그래프로 확장 가능한 토대를 만든다.**
   - 현재 실험 범위는 사용자 관련 개념, 대화 맥락, 프로젝트 관련 개념, 정정/수정 관계, 반복 선호 정도가 중심이다.
   - 하지만 구조 자체는 컴퓨팅 자원과 저장 용량이 충분하면 훨씬 더 큰 지식 그래프를 담을 수 있는 방향을 지향한다.

---

## MK5의 철학

### 1. 본체는 구조다
MK5에서 본질은 “문장 생성”이 아니라 “구조 형성”이다.
- 원문은 provenance로 남는다.
- 영구 그래프에는 재사용 가능한 의미블록이 저장된다.
- 응답은 이 구조의 결과를 언어로 치환한 표면이다.

### 2. 기본은 구조 보존이다
새로운 구조가 들어오더라도, 기존 연결을 즉시 부수지 않는다.
- 기본은 기존 구조를 유지한다.
- 다만, 기존 구조를 깨야만 설명 가능한 반례가 반복적으로 누적되면 trust를 낮춘다.
- trust가 임계점 밑으로 내려가면 revision candidate가 되고, 필요하면 구조를 교체한다.

즉 MK5는 완고한 고정 구조도 아니고, 아무거나 쉽게 뒤집는 구조도 아니다.

### 3. 설명형 conclusion이 본체다
MK5의 사고 결과는 설명형 `CoreConclusion`으로 남는다.
- `activated_concepts`는 node id 참조 목록이다.
- `key_relations`는 edge id 참조 목록이다.
- `detected_conflicts`, `trust_changes`, `revision_decisions`를 통해 구조적 판단이 남는다.

### 4. 행동형은 파생 출력이다
행동형 계획이나 “다음으로 무엇을 할지”는 설명형 conclusion 위에 얹힌다.
이 순서를 지켜야 구조 디버깅과 의미 보존이 가능하다.

### 5. 언어화는 사고가 아니다
언어화 모델은 세계를 이해하는 주체가 아니다.
이미 만들어진 conclusion을 자연어로 다듬어 표현하는 역할만 맡는다.
현재는 template verbalizer가 있고, 이후 작은 로컬 LLM을 언어화 전용으로 붙일 수 있다.

---

## 현재 구현 상태

### 구현 완료
- SQLite 스키마와 repository 계층
- Graph ingest
- 국부 활성화(`ThoughtView`)
- 충돌 감지 / trust 하락 / revision 검토
- 설명형 core conclusion 생성
- template verbalizer
- chat end-to-end pipeline
- 최소 Flask API 셸
- 기본 chat UI
- integration tests

### 아직 미완료
- Flask 실서버 기동 검증
- `requirements.txt`
- debug UI 패널화
- 행동형 derived plan
- local LLM verbalizer
- meaning block 정교화
- revision 고도화

---

## 현재 폴더 구조
```text
MK5/
├─ app/
├─ core/
│  ├─ activation/
│  ├─ cognition/
│  ├─ entities/
│  ├─ thinking/
│  ├─ update/
│  └─ verbalization/
├─ storage/
│  ├─ repositories/
│  └─ sqlite/
├─ tests/
├─ run.py
└─ README.md
```

---

## 현재 주요 흐름
1. 사용자 입력 수신
2. `GraphIngestService`가 chat_message / graph_event / node / edge / pointer 기록
3. `ActivationEngine`이 현재 입력 기준 seed block / seed node / local graph 생성
4. `ThoughtEngine`이 contradiction / trust / revision 검토 수행
5. `ConclusionBuilder`가 설명형 `CoreConclusion` 생성
6. `TemplateVerbalizer`가 응답 문자열 생성
7. UI에 응답과 debug 정보 표시

---

## 실행
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

## 다음 우선 작업
1. debug UI 패널화
2. `requirements.txt` 추가
3. 행동형 derived plan
4. local LLM verbalizer
5. meaning block / revision 정교화

---

## 주의
- 현재 기준으로 `project/profile/chat`을 별도 도메인으로 나누지 않는다.
- 모든 입력은 기본적으로 chat 흐름으로 들어오고, project나 profile은 그 그래프 안에서 해석되는 구조다.
- zip 업로드는 sync용일 뿐, 기준본은 항상 현재 로컬 작업본이다.
