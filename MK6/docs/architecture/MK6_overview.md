# MK6 아키텍처 개요

작성: 2026-04-20  
상태: 설계 단계

---

## 한 줄 요약

MK6는 언어를 그래프 주소로 변환하고, 임시 사고 그래프에서 사고한 뒤, 다시 언어로 출력하는 파이프라인이다.

---

## MK5와의 차이

| 항목 | MK5 | MK6 |
|---|---|---|
| 노드 정체성 | 텍스트 레이블 | 그래프 구조 위치 (텍스트는 부속 레이블) |
| 언어→의미 변환 | 여러 컴포넌트에 분산 | 단일 함수 `LangToGraph` |
| 입력 처리 | ingest (그래프에 저장) | 주소 탐색 → 없으면 EmptySlot 마킹 |
| 검색 발생 시점 | Think 이후 (ScopeGate 판정) | Think 루프 내부 (필요 시) |
| 검색 목적 | 그래프 보강 | 빈 곳·근거 부족·업데이트 필요 시 보충 |
| Think 구조 | 최대 3회 루프 (검색과 교차) | 루프 (검색 내포, 필요 횟수만큼) |
| 사고 공간 | 세계그래프 직접 조작 | 임시 사고 그래프 / 세계그래프 분리 |
| AI 의도 표현 | IntentManager snapshot | 목표 노드 + 입력 의도 임시 연결 |
| 개념 형성 | 미구현 | 공통부 추출 + 개념 분화 (LocalSubgraph 기반) |
| 도구 | 없음 | 파일/코드 도구 레이어 (2차) |

---

## 세계그래프 vs 임시 사고 그래프

**세계그래프 (World Graph):**
- SQLite `nodes` / `edges` / `words` 테이블에 영구 저장되는 인지 그래프
- Think 과정 중 즉시 수정되지 않는다
- "업데이트 필요"로 판단된 시점에만 반영된다
- 초기에는 업데이트가 활발하고, 그래프가 성숙할수록 빈도가 줄어든다

**임시 사고 그래프 (Temporary Thought Graph):**
- Think 루프 동안 메모리 상에서만 존재하는 작업용 그래프
- 세계그래프의 국소 서브그래프들을 복사해 구성한다
- 연결/해제, 병합/분할이 자유롭게 일어나며 세계그래프에 즉시 영향을 주지 않는다
- Think가 끝나면 세계그래프 반영 여부를 판단하고 필요한 부분만 커밋한다

---

## AI 의도 구조

```
목표 노드 (Goal Node)
  │  ← 임시 연결 (think 시작 시 구성)
  ▼
사용자 입력 의도 국소그래프 (TranslatedGraph 기반)
```

- **목표 노드**: 세계그래프에 기본 노드로 존재하는 고정 앵커
- **입력 의도**: LangToGraph로 번역된 사용자 입력의 국소그래프 집합
- Think는 "목표 노드에 임시 연결된 입력 의도를 만족하는가"를 기준으로 사고를 진행한다
- 목표 노드 이하의 구조는 향후 교체/확장 가능하도록 설계한다

---

## 전체 파이프라인

```
언어입력
  │
  ▼
InputTypeClassifier
  → "natural" | "code" | "path" | "url"
  → 비자연어: 전체를 단일 단위로 임베딩 폴백
  │
  ▼ (자연어 경로)
LangToGraph(user_input)
  → TranslatedGraph {
      nodes: [ConceptPointer | EmptySlot, ...]
      edges: [TranslatedEdge, ...]   ← 초기 neutral, 세계그래프 미반영
    }
  ※ EmptySlot은 마킹만 하고 반환 — 이 시점에 검색하지 않는다
  │
  ▼
임시 사고 그래프 구성
  → TranslatedGraph의 ConceptPointer들로 국소 서브그래프 합산
  → 목표 노드 + 입력 의도 임시 연결
  │
  ▼
Think 루프 (필요 횟수만큼)
  ├── 임시 사고 그래프에서 Edge 조작 (연결/해제/병합/분할)
  ├── 목표 의도 만족 여부 판단
  ├── 필요 시 검색:
  │     조건: EmptySlot 존재 | 근거 부족 | 업데이트 필요
  │     경로: 그래프 → 단어 → 외부 검색 → LangToGraph(검색결과)
  │           └─ 결과 없으면 None → "검색결과 없음"으로 수용
  ├── 세계그래프 업데이트 필요 시점 판단 → 커밋
  └── 수렴 판단 → 수렴하면 루프 종료
  │
  ▼
ConceptDifferentiation  ← Think 루프 내 또는 종료 직후
  → 임시 사고 그래프 내 유사 노드 쌍 탐지 (LocalSubgraph 비교)
  → 공통 의미 노드 생성 (구조만, 레이블 없음)
  → 필요 시 세계그래프 반영
  │
  ▼
ConclusionView 구성
  → 최종 임시 사고 그래프에서 룰 기반 노드/엣지 선별
  │
  ▼
GraphToLang(conclusion_view)
  → 각 노드를 연결된 words 테이블의 단어들로 표현
  → 레이블 없는 추상 노드: 이웃 노드의 단어들과 엣지 관계로 간접 표현
  → LLM Verbalizer가 최종 언어 생성
  │
  ▼
언어출력
  │
  ▼
Assistant Ingest
  → LangToGraph(응답)을 거쳐 세계그래프에 반영
```

---

## 핵심 원칙

### 1. 그래프가 의미다

노드는 텍스트 레이블이 아니라 그래프 내 위치(연결, 가중치, trust, edge 구조)로 의미를 가진다.  
텍스트 레이블은 노드에 붙는 부속 표현이고, 여러 개가 공존할 수 있다(다국어 가능).  
"십자가"라는 단어가 의미를 정의하는 것이 아니라, 십자가 개념의 그래프 연결 구조가 의미다.

### 2. LangToGraph는 번역이다

`LangToGraph`는 언어를 그래프 구조로 번역하는 함수다.  
저장(ingest)이 아니라 번역(translation)이다.  
찾지 못한 개념은 EmptySlot으로 마킹하고 반환한다. 검색은 Think 루프 내부에서 필요 시 발생한다.

### 3. 사고는 임시 그래프에서, 세계는 필요 시에만

Think는 임시 사고 그래프에서만 자유롭게 조작한다.  
세계그래프는 "이 업데이트가 필요하다"는 판단이 섰을 때만 반영된다.  
이 분리가 가역적 사고를 가능하게 한다.

### 4. 개념은 체감으로 형성된다

동일한 개념이 여러 번 다른 표현으로 입력될 때, 공통부가 추출되고 개념 노드가 형성된다.  
단번에 정해지지 않는다. 반복 입력 → 공통부 추출 → 분화 → 수렴의 과정으로 정착된다.

### 5. 언어는 출구이자 입구다

입력 언어는 `LangToGraph`로 그래프 주소로 변환되고,  
출력 언어는 `GraphToLang`으로 그래프 구조에서 파생된다.

---

## 컴포넌트 목록 (설계 기준)

| 컴포넌트 | 역할 | MK5 대응 |
|---|---|---|
| `InputTypeClassifier` | 자연어/코드/경로/URL 분류 | 없음 (신규) |
| `LangToGraph` | 언어 → TranslatedGraph (번역) | InputSegmenter + HashResolver 부분 |
| `GraphToLang` | 그래프 → 언어 | OllamaVerbalizer |
| `TempThoughtGraph` | 임시 사고 그래프 구성/조작 | ThoughtView (확장) |
| `WorldGraph` | 세계그래프 영구 저장/커밋 | GraphIngestService + GraphCommitService |
| `ThoughtEngine` | Think 루프 / 의도 판단 / 검색 내포 | ThoughtEngine |
| `SearchFunction` | 그래프→단어→검색→LangToGraph 경로 | SearchSidecar |
| `ConceptDifferentiation` | LocalSubgraph 기반 공통부 추출 + 분화 | 미구현 (MK5에서 이관) |
| `ConclusionViewBuilder` | 결론 구조 선별 | ConclusionViewBuilder |
| `ToolLayer` | 파일/코드 도구 실행 | 없음 (신규, 2차) |

---

## 도구 레이어 (2차 과제)

MVP에는 포함하지 않지만, 아키텍처는 도구 레이어를 수용할 수 있게 설계한다.

```
Tool interface:
  execute(tool_name: str, args: dict) → ToolResult

초기 도구 후보:
  - FileReader: 로컬 파일 읽기
  - CodeEditor: 로컬 코드 수정

연동 방식:
  ThoughtEngine이 tool_needed 판단
  → ToolLayer.execute()
  → ToolResult를 LangToGraph로 변환 후 TempThoughtGraph에 반영
```

ThoughtEngine은 도구 실행 여부를 판단하지만, 도구 자체는 교체 가능한 외부 모듈이다.

---

## 미결 설계 결정

| 항목 | 내용 |
|---|---|
| ConceptDifferentiation 임계치 | 유사도 판정 threshold 값 |
| Think 루프 수렴 판단 기준 | 목표 의도 만족을 어떻게 수치화할지 |
| 세계그래프 커밋 판단 기준 | Think 중 "업데이트 필요" 판단을 규칙으로 할지 LLM으로 할지 |
| 한글 1자 토큰 노이즈 처리 | 독립 조사(이/가/을)를 필터링할지 여부 |
| ThoughtEngine 도구 판단 방식 | LLM 판단인지 규칙 기반인지 (2차) |
