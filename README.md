# MACHI

MACHI는 단순한 챗봇 저장소가 아니라, 한 사람을 장기적으로 이해하고 보조하는 로컬 인지 시스템을 만들기 위한 실험 저장소입니다.

핵심 목표는 "그럴듯한 답변 생성"보다 아래에 있습니다.

- 사용자를 장기적으로 이해하는 구조 만들기
- 수정 가능한 기억(memory) 계층 만들기
- 언어 뒤에 있는 의미 구조와 판단 흐름 다루기
- 로컬 환경에서 통제 가능한 개인용 AI 아키텍처 만들기

이 저장소는 하나의 완성품보다, 그 목표를 향해 진행된 여러 세대의 설계와 구현을 함께 담고 있습니다.

---

## 저장소를 어떻게 읽으면 좋은가

루트 기준으로 보면 `IDEA1`부터 `MK6`까지가 각각 다른 단계의 실험입니다.

- `IDEA1`: Cognitive Partner 철학과 인지 구조 아이디어의 출발점
- `MK1`: 로컬 에이전트 형태의 초기 프로토타입
- `MK2`: evidence-first memory 계층 구축
- `MK3`: memory 중심 구조를 실제 대화 루프에서 안정화
- `MK4`: 그래프 자체를 사고 본체로 두는 graph-first thinking loop
- `MK5`: `MK4`의 일부 아이디어를 가져오되, 그래프를 장기 기억과 회수 인프라로 단순화하고 파일/문서/이미지/검색/터미널 도구를 오케스트레이션하는 현재 실행형 에이전트
- `MK6`: 언어 표면을 `LANG_GRAPH`로 segment화하고, 그 결과를 `CONCEPT_GRAPH`로 넘기는 다음 실험

즉, 이 레포는 "버전 업된 단일 앱"이라기보다, MACHI라는 큰 목표를 향해 아키텍처를 계속 재구성해 온 기록에 가깝습니다.

---

## 지금 시점의 핵심 해석

현재 이 저장소에는 두 개의 중요한 후속 축이 함께 있습니다.

### 1. `MK5`: 그래프 메모리 + 도구 오케스트레이션 축

`MK5`는 그래프를 사고 엔진 본체로 직접 돌리기보다, **사용자별 장기 기억과 회수 인프라**로 둡니다. 실제 응답 계획, 도구 사용 판단, 최종 답변 생성은 대화 LLM이 맡고, 그래프는 그 LLM을 보조하는 기억 계층으로 작동합니다.

이 축의 관심사는 주로 다음과 같습니다.

- 사용자별 persistent anchor
- SQLite 기반 장기 그래프 저장소
- 사용자 발화, 중요 사실, 검색 결과, correction/conflict 단서 저장
- 기억 요약, 그래프 조회, 웹/최신 정보 검색, 시장 스냅샷, 파일 CRUD, PDF/DOCX 문서 읽기, 이미지 분석, 터미널 실행을 LLM이 필요할 때 호출하는 구조
- 검색은 문장 전체가 아니라 그래프에서 얻은 노드 단위 후보를 함께 사용하는 방향
- 모델 입력에는 전체 도구 schema를 매번 넣지 않고, 짧은 도구 목록과 필요 시 읽는 `tool_manual`을 사용해 컨텍스트를 압축하는 방향

한마디로 말하면, **LLM + 도구 오케스트레이션 위에 수정 가능한 그래프 기억을 붙이는 실행형 에이전트**입니다.

### 2. `MK6`: 언어 그래프와 개념 그래프 분리 축

`MK6`는 완성된 대화 에이전트라기보다, 입력 문장을 곧바로 일반 토큰으로 자르지 않고 **문자 흐름 기반의 `LANG_GRAPH`에서 segment를 만들고**, 그 segment 리스트를 별도의 `CONCEPT_GRAPH`로 넘기는 실험입니다.

이 축의 관심사는 주로 다음과 같습니다.

- `LANG_GRAPH`가 글자 흐름과 substring overlap을 이용해 segment 후보를 형성하는 구조
- `LANG_GRAPH`와 `CONCEPT_GRAPH`의 저장 구조 분리
- `CONCEPT_GRAPH`가 segment 리스트를 받아 이후의 기억, 연결, 사고를 담당하는 구조
- 언어 표면 구조를 개념 그래프 입력으로 넘기는 전처리 계층 실험

한마디로 말하면, **생각 이전의 언어 표면 구조를 그래프로 다루고, 그 결과를 개념 그래프로 넘기는 실험**입니다.

---

## MACHI가 일관되게 지향하는 것

버전이 바뀌어도 아래 방향은 계속 유지됩니다.

### 1. Local-first

기억, 구조, 사용자 모델의 소유권이 가능한 한 로컬에 남는 시스템을 지향합니다.

### 2. Structure before comfort

좋은 말투보다, 먼저 구조적으로 맞는 이해와 설명을 더 중요하게 봅니다.

### 3. Memory is revisable

기억은 append-only 로그가 아니라, evidence와 correction으로 수정 가능한 계층이어야 합니다.

### 4. User model over shallow personalization

단순 취향 저장보다, 사용자의 판단 기준과 반복 패턴을 장기적으로 이해하는 쪽을 더 중요하게 봅니다.

### 5. The user remains the decision owner

MACHI는 사용자를 대신 판단하는 시스템이 아니라, 더 정교한 판단을 돕는 파트너를 목표로 합니다.

---

## 디렉터리 개요

루트에는 아래와 같은 주요 폴더가 있습니다.

```text
MACHI/
├── IDEA1/      # 초기 철학, Cognitive Partner 개념, 기억/정체성 문서
├── MK1/      # 초기 로컬 에이전트 프로토타입
├── MK2/      # memory 계층 실험
├── MK3/      # memory 기반 대화 루프 안정화
├── MK4/      # graph-first thinking loop 실험
├── MK5/      # graph memory + tool-using agent 구현
└── MK6/      # LANG_GRAPH + CONCEPT_GRAPH 실험
```

실행 가능한 최신 프로토타입을 보려면 보통 `MK5` 또는 `MK6`부터 읽는 것이 가장 효율적입니다.

---

## 어디서 시작하면 좋은가

목적에 따라 시작점을 다르게 잡는 것이 좋습니다.

### 철학과 문제의식부터 보고 싶다면

1. 루트 `README.md`
2. `IDEA1/README.md`
3. `MK1/README.md`

### memory 계층의 흐름을 보고 싶다면

1. `MK2/README.md`
2. `MK3/README.md`

### 그래프 사고 아키텍처의 흐름을 보고 싶다면

1. `MK4/`
2. `MK5/README.md`
3. `MK5/docs/architecture.md`

### 현재 가장 실용적인 실행 축을 보고 싶다면

1. `MK5/README.md`
2. `MK5/run_server.py`
3. `MK5/app/`, `MK5/core/`, `MK5/tools/`

### 언어 segment와 개념 그래프 분리 실험을 보고 싶다면

1. `MK6/LANG_GRAPH/README.md`
2. `MK6/LANG_GRAPH/lang_graph.py`
3. `MK6/CONCEPT_GRAPH/concept_graph.py`

---

## 빠른 실행 위치

루트에서 바로 실행하는 단일 엔트리포인트는 없고, 각 세대가 독립적인 작업 디렉터리를 가집니다.

대표적으로:

- `MK5`
  - `run_server.py`
- `MK6`
  - `run_server.py`

실행 전에는 해당 폴더의 README와 의존성 파일을 먼저 확인하는 것이 안전합니다. 현재 루트 기준으로는 `MK5/README.md`와 `MK5/requirements.txt`, 그리고 `MK6/LANG_GRAPH/README.md`가 주요 출발점입니다.

---

## 이 저장소를 한 문장으로 요약하면

MACHI는 "잘 답하는 챗봇"을 만드는 프로젝트라기보다, **사용자와 세계를 구조적으로 이해하고 장기 기억을 다룰 수 있는 로컬 개인 인지 시스템**을 만들기 위한 아키텍처 실험 저장소입니다.
