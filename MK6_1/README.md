# MK6_1

`MK6_1`은 Ollama, SQLite, 그래프 기반 추론 루프를 묶은 로컬 대화 실험 버전입니다.  
입력을 바로 문장으로만 다루지 않고 `입력 그래프 -> 사고 루프 -> 결론 그래프`로 처리하며, 필요할 때만 검색을 호출하고 검색 결과도 다시 그래프로 편입합니다.

## 현재 동작 요약

- `LangToGraph`가 사용자 입력을 `TranslatedGraph`로 변환합니다.
- `ThoughtEngine`가 입력 그래프를 바탕으로 로컬 추론을 돌립니다.
- 검색 조건은 기존 정책을 유지합니다.
  - `EmptySlot`이 있을 때 검색
  - `EmptySlot`은 없지만 관계 근거가 부족한 경우 no-slot search
- 검색은 이제 문장 통검색이 아니라 선택된 슬롯/포커스 라벨 중심 query를 사용합니다.
- 검색 결과 텍스트는 다시 `lang_to_graph()`에 태워 검색 결과 그래프를 만듭니다.
- 검색 결과 그래프 노드들은 현재 활성 로컬 그래프와 `search_graph_bridge` 계열 edge로 연결됩니다.
- 검색 결과는 기존 commit 정책을 따라 세계 그래프(`memory.db`)에도 반영됩니다.
- GraphToLang에는 이제 3개 섹션이 분리되어 전달됩니다.
  - `input_graph`
  - `conclusion_graph`
  - `search_graph`
- 사용자 자기서술과 정정은 이름 하드코딩 없이 assertion 구조로 처리합니다.
  - `profile_reference`, `identity_surface`
  - `user_assertion`
  - `user_correction_conflict`

## 주요 파일

- `run_cli.py`: CLI 실행기
- `run_server.py`: FastAPI 서버 실행기
- `app/server.py`: `/`, `/chat`, `/models`, `/health`
- `app/pipeline.py`: 전체 파이프라인 연결
- `core/translation/lang_to_graph.py`: 입력을 로컬 그래프로 변환
- `core/thinking/thought_engine.py`: 검색, 추론, commit
- `core/thinking/claim_graph.py`: assertion / correction / conflict 처리
- `core/verbalization/answer_contract_clean.py`: GraphToLang용 3섹션 contract 생성
- `tools/ollama_client.py`: Ollama chat / embedding / model list
- `data/memory.db`: SQLite world graph

## 요구 사항

- Python 3.12 이상 권장
- 로컬 [Ollama](https://ollama.com/) 실행 중
- 생성 모델 1개 이상
- 임베딩 모델 1개 이상

기본 설정:

- 생성 모델: `gemma3:4b`
- 임베딩 모델: `nomic-embed-text`
- Ollama 주소: `http://localhost:11434`
- DB 경로: `data/memory.db`

## 처음 실행

### 1. 의존성 설치

```bash
python -m pip install -r requirements.txt
```

### 2. Ollama 실행

```bash
ollama serve
```

이미 Ollama 앱이 백그라운드에서 떠 있다면 생략해도 됩니다.

### 3. 모델 설치

```bash
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

`gemma3:4b` 다운로드 명령은 그대로 `ollama pull gemma3:4b` 입니다.

## 실행 방법

### CLI

```bash
python run_cli.py
```

종료:

- `exit`
- `quit`
- `Ctrl+C`

### 서버

```bash
python run_server.py
```

예시:

```bash
python run_server.py --host 127.0.0.1 --port 8000 --reload
```

기본 주소:

- UI: `http://127.0.0.1:8000/`
- Health: `http://127.0.0.1:8000/health`
- Models: `http://127.0.0.1:8000/models`

## `/chat` 응답 흐름

1. 입력을 `TranslatedGraph`로 변환
2. direct input / empty slot / local context를 바탕으로 `TempThoughtGraph` 구성
3. 필요 시 검색 수행
4. 검색 결과를 그래프화하고 현재 로컬 그래프와 연결
5. 새 노드/에지를 세계 그래프에 commit
6. `ConclusionView` 생성
7. GraphToLang에 아래 3개 그래프를 분리 전달
   - 사용자 입력 그래프
   - 결론 그래프
   - 검색 결과 그래프
8. Ollama 생성 모델이 최종 한국어 답변 생성

## 검색 관련 변경 사항

### 1. 검색 query 생성

예전처럼 사용자 문장 전체를 우선으로 넣지 않습니다.

- `EmptySlot` 검색:
  - 중요도가 높은 slot만 선택
  - slot hint를 정규화해 중복 제거 후 query 생성
- no-slot 검색:
  - 입력 그래프의 중심 라벨 또는 현재 focus 라벨을 우선 사용
  - 관계 근거가 이미 충분하면 검색 생략

### 2. 검색 결과 그래프화

검색 결과는 이제 단순 요약 텍스트가 아니라 그래프로 들어갑니다.

- 결과 title / snippet에서 노드 생성 또는 기존 노드 재사용
- 결과 간 공기 관계를 search provenance edge로 연결
- 검색 결과 전체를 `search_graph` 섹션으로 분리
- 현재 활성 로컬 그래프와 bridge edge로 연결

### 3. 세계 그래프 반영

검색 결과 그래프도 기존 commit 정책을 따릅니다.

- 새 strong node / edge는 `memory.db`에 반영
- weak / temporary 구조는 그대로 보수적으로 처리
- 검색 결과가 이미 존재하던 노드를 다시 가리키면 재사용 및 강화

## 자기서술 / 정정 처리

### 자기서술

사용자 자기소개는 별도 이름 휴리스틱으로 처리하지 않습니다.

- 현재 입력에서 direct match된 concept
- 활성화된 `ProfileActivationView`
- `identity_surface`, `profile_reference`

를 바탕으로 subject binding을 잡습니다.

### 정정

정정 여부를 `"아니야"`, `"정정"` 같은 문자열 패턴으로 판단하지 않습니다.

현재 방식은 assertion replacement 기반입니다.

- 현재 user assertion의 subject/object를 추출
- 직전 assistant assertion state와 비교
- 같은 subject에 대해 이전 object를 새 object가 대체하면:
  - 이전 object 쪽에 `user_correction_conflict`
  - 새 object 쪽에 `user_assertion`
  - 이전 assertion edge에는 conflict pressure 반영

즉, 정정은 문장 cue가 아니라 `이전 주장과 현재 주장 사이의 구조적 대체 관계`로 처리합니다.

## GraphToLang 3섹션 규약

GraphToLang에는 하나의 뭉친 텍스트 대신 아래 3개 그래프가 분리되어 들어갑니다.

- `input_graph`
  - 사용자 입력에서 직접 나온 구조
  - speaker=`user`
- `conclusion_graph`
  - 사고 루프가 선택한 결론 구조
  - speaker=`system`
- `search_graph`
  - 검색으로 유입된 외부 근거 구조
  - speaker=`external`

중요 규칙:

- user self-claim을 assistant 1인칭으로 바꾸면 안 됨
- `conclusion_graph`가 우선
- `search_graph`는 보강 근거
- `conclusion_graph`가 비면 `input_graph`와 `search_graph`를 참고

## 환경 변수

- `OLLAMA_HOST`
- `OLLAMA_MODEL_NAME`
- `EMBEDDING_MODEL_NAME`
- `MK6_DB_PATH`
- `OLLAMA_TIMEOUT_SECONDS`
- `EMBEDDING_TIMEOUT_SECONDS`

PowerShell 예시:

```powershell
$env:OLLAMA_MODEL_NAME="gemma3:12b"
$env:EMBEDDING_MODEL_NAME="nomic-embed-text"
python run_server.py
```

## 자주 겪는 문제

### 1. `404 Not Found` for `/api/embeddings`

현재 `tools/ollama_client.py`는 다음 두 경로를 순서대로 시도합니다.

- `/api/embeddings`
- `/api/embed`

둘 다 실패하면 보통 아래 셋 중 하나입니다.

1. Ollama가 실제로 안 떠 있음
2. `OLLAMA_HOST`가 잘못됨
3. 임베딩 모델이 설치되지 않음

확인:

```bash
ollama list
curl http://localhost:11434/api/tags
```

### 2. 임베딩 모델 미설치

기본 임베딩 모델:

```bash
ollama pull nomic-embed-text
```

다른 임베딩 모델을 쓸 경우:

```powershell
$env:EMBEDDING_MODEL_NAME="your-embedding-model"
python run_server.py
```

### 3. 모델은 있는데 `/models`에 안 보임

임베딩 전용 모델은 생성 모델 선택지에서 제외될 수 있습니다.  
이는 `OLLAMA_EXCLUDED_MODELS` 정책과 응답 가능 여부 검증 때문입니다.

## 테스트

단일 예시:

```bash
python -m pytest .\tests\test_ollama_client.py
python -m pytest .\tests\test_search_result_graphization.py
python -m pytest .\tests\test_answer_contract_sections.py
python -m pytest .\tests\test_claim_graph_correction.py
```

전체:

```bash
python -m pytest
```

## 참고 문서

- `docs/architecture/file_structure.md`
- `docs/architecture/graph_schema.md`
- `docs/architecture/lang_to_graph.md`
- `docs/architecture/claim_assertion_graph.md`
