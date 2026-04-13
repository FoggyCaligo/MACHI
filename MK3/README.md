# MK3

MK3는 MACHI가 **로컬 도구형 개인 AI**에 가까워지던 단계입니다.

이 버전은 MK1, MK2에서 정리된 Cognitive Partner / 운영 규칙 아이디어를 바탕으로,

- 로컬 LLM
- trusted search
- 간단한 프로필
- 최근 대화 메모리

를 하나의 실제 에이전트 형태로 묶으려던 실험입니다.

## 이 버전의 핵심

MK3의 중심은 **"검색 가능한 로컬 에이전트"** 입니다.

- 로컬 모델로 답변을 생성하고
- 최신성이나 근거가 필요하면 `trusted_search.py`를 통해 검색을 보강하고
- 간단한 profile + recent conversation memory를 함께 사용하는 구조입니다

즉, MK3는 memory를 아주 깊게 재구성한 단계라기보다,
**검색 + 응답 + 최소 개인화** 를 갖춘 로컬 개인 AI 프로토타입에 가깝습니다.

## 주요 파일

- `app.py`
  - FastAPI 엔트리포인트
- `agent.py`
  - 에이전트 응답 흐름
- `trusted_search.py`
  - 신뢰 도메인 중심 검색
- `memory.py`
  - 단순 memory 계층
- `system_prompt.txt`
  - 사용자 작동 방식에 맞춘 system prompt
- `data/user_profile.json`
  - 간단한 프로필 데이터
- `data/chat_history.db`
  - 최근 대화 메모리

## 이 버전의 위치

MACHI 전체 흐름에서 MK3는:

- MK2의 운영 규칙 기반을 실제 앱 형태로 옮긴 단계
- 최신성/근거 확인을 search와 연결한 단계
- MK4 이전의 **search + prompt + light memory** 중심 버전

으로 이해하면 가장 자연스럽습니다.

즉, MK3가 "검색 가능한 개인 AI" 쪽 실험이었다면,
`MK4`는 그 다음 단계에서 **evidence-first memory와 correction 가능한 기억 구조**를 더 깊게 밀어붙이는 버전입니다.

## 간단 실행

이 폴더는 기본적으로 로컬 Ollama 환경을 전제로 합니다.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app:app --reload
```

브라우저:

```text
http://127.0.0.1:8000/docs
```
