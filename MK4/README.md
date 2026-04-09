# MK4 SQLite Implementation (Phase 1.5)

MK4는 **사용자 모델을 보수적으로 형성·교정·회수하는 로컬 개인화 인지 시스템**입니다.
이 버전은 SQLite 기반 메모리 구조와 artifact/project 기반 분석 흐름을 함께 포함합니다.

## 현재 포함 기능
- raw message 저장
- profile / correction / episode / summary / state 저장
- response retrieval
- recall retrieval + 원문 확장 조회(1차)
- correction 기반 topic-scoped profile rebuild
- retention policy (profile history 2, correction queue 5, episode aging)
- artifact/project ingest
- project 기반 질의응답
- project artifact에서 profile evidence 추출
- evidence/candidate 기반 confirmed profile 승격 1차
- UI에서 로컬 Ollama 모델 목록 조회 및 선택

## 사전 준비
### 1) Python 가상환경
Python 3.11+ 권장.

### 2) Ollama 설치
이 저장소는 **Ollama가 먼저 설치되어 있어야** 동작합니다.

- Windows: Ollama 설치 프로그램으로 설치
- 설치 후 터미널에서 `ollama` 명령이 실행되어야 함

### 3) 사용할 모델 준비
기본 모델은 `qwen2.5:3b`입니다.

```bash
irm https://ollama.com/install.ps1 | iex
ollama --version
ollama ps

ollama pull qwen2.5:3b
```

다른 모델을 UI에서 고르려면, 그 모델도 미리 pull 되어 있어야 합니다.

예:

```bash
ollama pull gemma3:1b
ollama pull qwen2.5:1.5b
ollama pull gemma4:e2b
ollama pull gemma4:26b-a4b-it-q4_K_M
ollama pull llama3.2:3b

```

## 설치
### Windows Git Bash
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

### Windows PowerShell
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 실행
### Git Bash / PowerShell 공통
```bash
python -m uvicorn app.api:app --reload
```

브라우저:

```text
http://127.0.0.1:8000/ui
```

## UI 사용법
### 1) 모델 선택
- UI 상단의 모델 선택 박스에서 현재 PC에 설치된 Ollama 모델 중 하나를 선택 가능
- 선택값은 브라우저 localStorage에 저장됨
- `기본 모델 사용`을 누르면 서버 기본값(`qwen2.5:3b`)으로 되돌아감
- 모델 목록은 `모델 새로고침`으로 다시 불러올 수 있음

### 2) artifact/project 흐름
- **텍스트 파일**: 현재 메시지의 참고 자료로 첨부
- **ZIP 파일**: artifact/project로 업로드
- ZIP 업로드 후 생성된 `project_id`는 자동 저장됨
- 같은 `project_id` 안에서 프로젝트 질문과 프로필 질문을 함께 수행 가능

## 주요 API
- `GET /` : 서버 상태 확인
- `GET /ui` : 채팅 UI
- `GET /models` : 로컬 Ollama 모델 목록 조회
- `POST /chat` : 일반 채팅 / artifact 질문 / ZIP 업로드
- `GET /recall?query=...` : recall 조회

## /chat에서 받는 주요 form field
- `message`: 사용자 메시지
- `project_id`: 기존 artifact/project에 이어서 질문할 때 사용
- `model`: 선택적으로 특정 Ollama 모델 지정
- `file`: 텍스트 파일 또는 ZIP 파일

## GPU 사용 확인
GPU가 있는 컴퓨터라고 해서 항상 자동으로 빨라지는 것은 아닙니다.

확인 권장:

```bash
ollama ps
```

여기서 `PROCESSOR`가 GPU로 표시되는지 확인하세요.

## 현재 한계
- topic 분류는 아직 규칙 기반
- `trusted_search`는 아직 비활성 stub
- correction 적용은 최신 correction 우선 방식의 1차 버전
- evidence → confirmed profile 승격은 아직 보수적 1차 규칙 기반
- 코드 전용 모델 분리는 아직 미적용

## DB 관련 주의
실제 사용 DB는 다음 경로입니다.

```text
data/memory.db
```

루트의 `memory.db` 파일이 남아 있다면 현재 코드에서 쓰는 운영 DB가 아닐 가능성이 큽니다.
혼동 방지를 위해 백업 후 정리하는 것을 권장합니다.