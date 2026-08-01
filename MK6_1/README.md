# MK6_1

`MK6_1`은 로컬 Ollama와 SQLite 기반 메모리 그래프를 사용해 입력을 해석하고 응답을 생성하는 실험용 대화 시스템입니다. CLI로 바로 써볼 수 있고, FastAPI 서버와 간단한 웹 UI도 함께 제공합니다.

## 구성 요약

- `run_cli.py`: 터미널 대화형 실행기
- `run_server.py`: FastAPI 서버 실행기
- `app/server.py`: `/`, `/chat`, `/models`, `/health` 등 API/UI 진입점
- `app/pipeline.py`: 입력 처리 전체 파이프라인
- `tools/ollama_client.py`: Ollama chat / generate / embedding 호출
- `data/memory.db`: 기본 SQLite 저장소

## 요구 사항

- Python 3.12 이상 권장
- 로컬 [Ollama](https://ollama.com/) 실행 중
- Ollama 생성 모델 1개 이상
- Ollama 임베딩 모델 1개

기본 설정값은 다음과 같습니다.

- 생성 모델: `gemma3:4b`
- 임베딩 모델: `nomic-embed-text`
- Ollama 주소: `http://localhost:11434`

## 처음 실행할 때

### 1. Python 의존성 설치

`MK6_1` 폴더에서 실행:

```bash
python -m pip install -r requirements.txt
```

### 2. Ollama 실행

별도 터미널에서:

```bash
ollama serve
```

이미 백그라운드 서비스로 떠 있다면 이 단계는 건너뛰어도 됩니다.

### 3. 필요한 모델 설치

기본 생성 모델과 임베딩 모델을 쓰려면:

```bash
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

다른 생성 모델을 쓰고 싶다면 `OLLAMA_MODEL_NAME`만 바꿔도 됩니다. 다만 임베딩 단계는 별도 모델이 필요하므로 `nomic-embed-text` 또는 동일 용도의 임베딩 모델을 준비해야 합니다.

## 실행 방법

### CLI 실행

```bash
python run_cli.py
```

종료:

- `exit`
- `quit`
- `Ctrl+C`

### API 서버 실행

```bash
python run_server.py
```

옵션 예시:

```bash
python run_server.py --host 127.0.0.1 --port 8000 --reload
```

서버가 뜨면 기본 주소는 다음과 같습니다.

- UI: `http://127.0.0.1:8000/`
- Health: `http://127.0.0.1:8000/health`
- Models: `http://127.0.0.1:8000/models`

## API 빠른 예시

### 상태 확인

```bash
curl http://127.0.0.1:8000/health
```

### 모델 목록 확인

```bash
curl http://127.0.0.1:8000/models
```

### 채팅 요청

```bash
curl -X POST http://127.0.0.1:8000/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"message\":\"사과는 과일이야?\", \"model\": null, \"session_id\": \"default\"}"
```

응답 예시 필드:

- `response`
- `loop_count`
- `had_empty_slots`
- `node_count`
- `edge_count`
- `model_used`

## 환경 변수

주로 자주 바꾸게 되는 값들만 정리하면:

- `OLLAMA_HOST`: 기본값 `http://localhost:11434`
- `OLLAMA_MODEL_NAME`: 기본 생성 모델
- `EMBEDDING_MODEL_NAME`: 기본 임베딩 모델
- `MK6_DB_PATH`: DB 경로, 기본값 `data/memory.db`
- `OLLAMA_TIMEOUT_SECONDS`: 생성 요청 타임아웃
- `EMBEDDING_TIMEOUT_SECONDS`: 임베딩 요청 타임아웃

PowerShell 예시:

```powershell
$env:OLLAMA_MODEL_NAME="gemma3:12b"
$env:EMBEDDING_MODEL_NAME="nomic-embed-text"
python run_server.py
```

## 자주 겪는 문제

### `404 Not Found` for `/api/embeddings`

현재 코드에서는 Ollama 구버전 `/api/embeddings`와 신버전 `/api/embed`를 모두 시도합니다. 그래도 실패하면 Ollama 자체가 비정상이거나 주소가 잘못된 경우가 많습니다.

확인 순서:

1. `ollama serve` 또는 Ollama 앱이 실제로 실행 중인지 확인
2. `OLLAMA_HOST`가 `http://localhost:11434`와 일치하는지 확인
3. `curl http://localhost:11434/api/tags` 또는 `ollama list`로 연결 확인

### 임베딩 모델 관련 오류

기본 설정은 `nomic-embed-text`입니다. 설치되지 않았다면:

```bash
ollama pull nomic-embed-text
```

다른 임베딩 모델을 쓰려면:

```powershell
$env:EMBEDDING_MODEL_NAME="your-embedding-model"
python run_server.py
```

### 생성 모델이 기본값과 다를 때

현재 로컬에 `gemma3:4b`가 없고 다른 모델만 설치되어 있다면:

```powershell
$env:OLLAMA_MODEL_NAME="gemma3:12b"
python run_server.py
```

## 테스트

단일 테스트 예시:

```bash
python -m pytest .\tests\test_ollama_client.py
```

전체 테스트:

```bash
python -m pytest
```

## 참고

더 자세한 구조 설명은 아래 문서를 보면 됩니다.

- `docs/architecture/file_structure.md`
- `docs/architecture/graph_schema.md`
- `docs/architecture/lang_to_graph.md`
