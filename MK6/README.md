# MK6

작성: 2026-04-20  
상태: 구현 완료 (MVP)

---

## 정체성

MK6는 **개념 그래프 기반 인지 시스템**이다.

그래프를 "단어"가 아닌, **"그래프가 체감한 개념"** 으로서 정의한다.

MK5가 "언어체계에 올라간 장기기억 및 판단 구조"였다면,  
MK6는 **언어를 그래프 주소로 변환하고, 개념 그래프에서 사고한 뒤, 다시 언어로 출력**한다.

언어는 그래프 구조의 인터페이스다. 의미는 그래프 안에 있다.

---

## 핵심 변화 (vs MK5)

- `LangToGraph`: 언어 → 개념 포인터 집합 (번역, ingest 아님)
- 노드는 텍스트 레이블이 아니라 **그래프 구조 위치**가 의미
- 사고는 **임시 사고 그래프**에서만 — WorldGraph는 판단된 시점에만 반영
- 검색은 Think 루프 **내부**에서 필요 시 발생 (EmptySlot 존재 / 근거 부족)
- 공통부 추출 + 개념 분화(`ConceptDifferentiation`)로 **체감된 개념** 형성
- 파일/코드 도구 레이어 (2차)

---

## 파이프라인

```
언어입력
  │
  ▼
LangToGraph(user_input)
  → TranslatedGraph { nodes: [ConceptPointer | EmptySlot], edges: [...] }
  │
  ▼
TempThoughtGraph 구성
  → ConceptPointer들의 LocalSubgraph 합산
  → 목표 노드(Goal Node)에 임시 연결
  │
  ▼
Think 루프 (수렴까지, 최대 THINK_MAX_LOOPS)
  ├── EmptySlot → 검색 → LangToGraph(검색결과) → TempThoughtGraph 반영
  ├── ConceptDifferentiation (유사 개념 쌍 → 추상 공통 노드 생성)
  ├── 약한 커밋 (분화 결과 즉시 WorldGraph 반영)
  └── 수렴 판단: 그래프 수정 없음 OR 구조 변화 없음 → 종료
  │
  ▼
강한 커밋 (루프 종료 후, 신규 노드/엣지 WorldGraph 반영)
  │
  ▼
ConclusionView 구성
  │
  ▼
GraphToLang(ConclusionView)
  → 노드/엣지 구조 직렬화 → LLM Verbalizer → 언어 출력
  │
  ▼
(향후) Assistant Ingest: LangToGraph(응답) → WorldGraph 반영
```

---

## 실행
ollama에서 nomic-embed-text:latest 다운 필수.


```bash
# 대화형 CLI
python MK6/run_cli.py

# API 서버 (FastAPI)
python MK6/run_server.py [--host 0.0.0.0] [--port 8000] [--reload]

# 테스트 (MK6/ 안에서)
pytest
```

환경변수 설정 (`.env` 또는 shell):

```
MK6_DB_PATH=data/memory.db
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL_NAME=llama3
EMBEDDING_MODEL_NAME=nomic-embed-text
```

---

## 아키텍처 문서

- 전체 구조: `docs/architecture/MK6_overview.md`
- 파일 구조 및 컴포넌트: `docs/architecture/file_structure.md`
- LangToGraph 상세: `docs/architecture/lang_to_graph.md`
- 그래프 스키마: `docs/architecture/graph_schema.md`
- 개념 분화: `docs/architecture/concept_differentiation.md`
