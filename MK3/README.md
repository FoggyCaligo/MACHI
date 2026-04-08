# Gemma 4 26B A4B 로컬 에이전트

이 프로젝트는 다음 요구사항을 기준으로 작성되었습니다.

- 로컬 모델: Ollama의 `gemma4:26b-a4b-it-q4_K_M`
- 도구 호출: Ollama `/api/chat` tool calling
- 검색: Ollama Web Search API
- 신뢰도 정책: 공식문서/논문 우선, 그 외 도메인 제거
- 개인화: 간단한 프로필 + 최근 대화 메모리

## 1. 준비

### Ollama 모델 받기
```bash
ollama pull gemma4:26b-a4b-it-q4_K_M
```

### Python 환경
```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 환경변수
```bash
copy .env.example .env
```

`.env`에서 `OLLAMA_API_KEY`를 채우세요.

## 2. 실행
```bash
uvicorn app:app --reload
python -m uvicorn app:app --reload
```

브라우저에서:
```text
http://127.0.0.1:8000/docs
```

## 3. 동작 방식
1. 사용자 질문 입력
2. Gemma가 최신성/근거 필요 여부를 판단
3. 필요하면 `trusted_search` 호출
4. `trusted_search`는 Ollama web search 결과를 가져오고, 공식문서/논문 도메인만 남김
5. 가능한 경우 실제 페이지 본문을 fetch 해서 excerpt 추가
6. 결과를 Gemma에게 다시 넣고 최종 답변 생성

## 4. 기본 신뢰 도메인
- 공식문서: `ai.google.dev`, `docs.ollama.com`, `python.org`, `docs.python.org`, `fastapi.tiangolo.com`, `pytorch.org`, `huggingface.co`
- 논문: `arxiv.org`, `doi.org`, `aclanthology.org`, `proceedings.mlr.press`, `openreview.net`

`trusted_search.py`에서 원하는 도메인을 추가/삭제할 수 있습니다.

## 5. 주의
- 모델 추론은 로컬이지만, 웹 검색은 Ollama의 cloud-side Web Search API를 사용합니다.
- 완전 오프라인 검색이 필요하면 SearXNG + 자체 fetcher 조합으로 바꾸는 편이 낫습니다.
- PDF 원문 파싱, DOI 본문 추출, Crossref/PMC 통합은 아직 넣지 않았습니다. 필요하면 확장할 수 있습니다.
