# MK5

`MK5`는 그래프를 사고의 본체로 두던 흐름에서 한 걸음 물러나, **그래프를 기억 전용 인프라로 단순화하는 단계**다.

이전 구조는 그래프 위에서 직접 사고하는 데 강점이 있었지만, 그만큼 파이프라인이 무거워지고, 응답 경로가 복잡해지며, 유지보수 부담도 커진다. `MK5`는 이 문제를 해결하기 위해 그래프의 역할을 다시 줄인다.

핵심 생각은 단순하다. 그래프는 "생각하는 주체"가 아니라, **사용자와 세계에 대한 장기 기억을 저장하고 꺼내 오는 저장소**가 되면 된다.

## 목표

`MK5`의 목표는 다음과 같다.

> 그래프는 장기 기억과 회수만 맡고, 실제 응답 계획과 도구 사용 판단은 하나의 대화 LLM이 담당하게 만든다.

즉 이 단계가 고치려는 문제는 아래와 같다.

- 그래프 사고 루프가 기본 응답 경로를 너무 무겁게 만드는 문제
- 기억과 사고가 과하게 결합되어 구조가 복잡해지는 문제

## 기능

### 1. 사용자별 장기 기억

- 각 사용자에 대해 지속적인 anchor를 만든다.
- 같은 사용자 ID로 들어온 정보는 같은 장기 기억 아래에 누적된다.

### 2. 그래프 기반 기억 저장

- 사용자 발화
- 중요 사실
- 검색에서 얻은 정보
- correction / conflict 단서

이런 항목을 장기 그래프에 쌓는다.

### 3. 도구 기반 회수

- 그래프를 직접 사고 엔진처럼 돌리지 않는다.
- 필요할 때 LLM이 그래프 조회, 이웃 조회, 웹 검색 같은 도구를 호출한다.

### 4. 가벼운 응답 경로

- 기본 응답은 `현재 메시지 + 기억 요약 + 필요 시 도구 호출`로 간다.
- 복잡한 thought loop를 기본값으로 두지 않는다.

## 작동방식

`MK5`의 흐름은 아래와 같다.

```text
사용자 입력
-> user anchor 확인/생성
-> 발화 저장
-> 사용자 기억 요약 로드
-> LLM이 답변 계획 수립
-> 필요하면 graph search / web search / file tools 호출
-> 최종 답변 생성
-> 유용한 사실은 다시 그래프에 저장
```

즉 `MK5`에서는 그래프가 먼저 생각하고 LLM이 번역하는 것이 아니라, **LLM이 계획하고 그래프는 기억 저장소로 지원**한다.

## 기억구조

`MK5`의 기억 구조는 이전 세대보다 훨씬 단순하다.

### 1. 사용자 anchor

- 예: `user_anchor::<user_id>`
- 같은 사용자의 기억을 묶는 기준점 역할을 한다.

### 2. 장기 그래프 저장소

- SQLite 기반 그래프 저장소에 노드와 관계를 유지한다.
- 사용자 발화 흔적과 회수 가능한 사실이 여기에 누적된다.

### 3. 회수용 이웃 구조

- 현재 질문에 맞는 기억은 anchor 주변 이웃과 관련 노드 검색으로 가져온다.
- 그래프는 추론 본체가 아니라 retrieval substrate다.

### 4. Active graph context

- 이전 턴에서 실제로 활성화됐던 그래프 문맥을 세션 단위로 짧게 들고 간다.
- 동시에 현재 질문 기준으로 그래프를 새로 활성화한다.
- 이 둘은 각각 `Previous active graph context`, `Current graph activation`으로 LLM 입력에 들어간다.

즉 `MK5`의 기억 구조는 **사용자 anchor + 장기 그래프 + 도구 기반 회수 + 턴 단위 active graph context**로 요약할 수 있다.

## 실행방법

아래는 Windows PowerShell 기준으로, 빈 PC에서 새로 내려받아 실행하는 순서다.

### 1. 저장소 받기

```powershell
git clone https://github.com/FoggyCaligo/MACHI.git
cd MACHI\MK5
```

### 2. 가상환경 만들기

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Ollama 준비

기본 생성 모델은 `gemma3:4b`다.

```powershell
ollama serve
```

새 PowerShell 창에서:

```powershell
ollama pull gemma3:4b
```

### 4. 서버 실행

```powershell
python run_server.py
```

### 5. 접속 확인

브라우저에서 아래 주소를 연다.

```text
http://127.0.0.1:8010/
```

구현을 볼 때 시작점으로 좋은 파일은 아래다.

- `app/server.py`
- `core/agent/orchestrator.py`
- `core/graph/repository.py`
- `core/graph/service.py`
- `tools/graph_tools.py`
- `tools/web_search.py`
- `docs/architecture.md`

## 다른 레포에서 사용하기

`MK5`는 `playlist2` 같은 다른 레포에서 그래프 메모리와 도구 오케스트레이션 엔진으로 가져다 쓸 수 있다.

이때 호스트 레포별로 아래 경로를 분리해서 지정하는 것이 좋다.

- `MK5_WORKSPACE_ROOT`
- `MK5_DB_PATH`
- `MK5_SENTENCE_BREAKER_DB_PATH`

자세한 예시는 `docs/using_mk5_from_other_repo.md`를 참고하면 된다.

