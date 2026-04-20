# MK6 아키텍처 개요

작성: 2026-04-20  
상태: 설계 단계

---

## 한 줄 요약

MK6는 언어를 그래프 주소로 변환하고, 개념 그래프에서 사고한 뒤, 다시 언어로 출력하는 파이프라인이다.

---

## MK5와의 차이

| 항목 | MK5 | MK6 |
|---|---|---|
| 노드 정체성 | 텍스트 레이블 | 그래프 구조 위치 (텍스트는 부속 레이블) |
| 언어→의미 변환 | 여러 컴포넌트에 분산 | 단일 함수 `LangToGraph` |
| 입력 처리 | ingest (그래프에 저장) | 주소 탐색 → 없으면 EmptySlot |
| 검색 발생 시점 | Think 이후 (ScopeGate 판정) | LangToGraph 이후 (EmptySlot 기반, Think 이전) |
| 검색 목적 | 그래프 보강 | EmptySlot 채우기 → 그래프 안정화 |
| Think 구조 | 최대 3회 루프 (검색과 교차) | 단일 패스 (검색이 먼저 완료) |
| 개념 형성 | 미구현 | 공통부 추출 + 개념 분화 |
| 도구 | 없음 | 파일/코드 도구 레이어 (2차) |

---

## 전체 파이프라인

```
언어입력
  │
  ▼
LangToGraph(user_input)
  → [ConceptPointer | EmptySlot, ...]
  │  ├─ ConceptPointer: node_id + address_hash + local_subgraph
  │  └─ EmptySlot: concept_hint + unfound 플래그
  │
  ▼
EmptySlot 처리 — 검색은 여기서 발생 (Think 이전)
  ├─ EmptySlot이 있으면:
  │   QuestionSlotPlanner(concept_hint) → 검색 쿼리
  │   외부 검색 실행
  │   LangToGraph(검색결과) → ConceptPointer 교체 시도
  │
  └─ 여전히 빈 EmptySlot:
      GraphIngestService → 신규 노드 생성 (concept_hint를 임시 레이블로)
      → ConceptPointer로 교체
  │
  ▼
Activation
  → 모든 ConceptPointer의 local_subgraph 합산 → ThoughtView 구성
  → PatternDetector로 서브그래프 패턴 추가
  │
  ▼
Think (단일 패스)  ← 검색이 먼저 그래프를 안정화했으므로 루프 불필요
  ThoughtEngine.think()
    → ContradictionDetector
    → TrustManager
    → StructureRevisionService
    → IntentManager
    → CoreConclusion 생성
  │
  ▼
ConceptDifferentiation  ← Think 직후 실행
  → ThoughtView 내 유사 노드 쌍 탐지
  → 미니 그래프 비교 → 공통 의미 노드 생성 (구조만, 레이블 없음)
  │
  ▼
ConclusionView 구성
  → 최종 ThoughtView에서 룰 기반 노드/엣지 선별
  │
  ▼
GraphToLang(conclusion_view)
  → LLM Verbalizer가 그래프 구조에서 언어 생성
  │
  ▼
언어출력
  │
  ▼
Assistant Ingest
  → LangToGraph(응답)을 거쳐 그래프에 반영
```

---

## 핵심 원칙

### 1. 그래프가 의미다

노드는 텍스트 레이블이 아니라 그래프 내 위치(연결, 가중치, trust, edge 구조)로 의미를 가진다.  
텍스트 레이블은 노드에 붙는 부속 표현이고, 여러 개가 공존할 수 있다(다국어 가능).  
"십자가"라는 단어가 의미를 정의하는 것이 아니라, 십자가 개념의 그래프 연결 구조가 의미다.

### 2. LangToGraph는 ingest가 아니다

`LangToGraph`는 언어를 받아 그래프의 기존 개념 주소를 반환하는 탐색 함수다.  
"저장"이 아닌 "조회"다.  
찾지 못한 개념만 EmptySlot으로 표시되고, EmptySlot이 신규 ingest의 트리거가 된다.  
이 함수는 파이프라인 여러 지점에서 호출된다: 사용자 입력, 검색 결과, 어시스턴트 응답.

### 3. 개념은 체감으로 형성된다

동일한 개념이 여러 번 다른 표현으로 입력될 때, 공통부가 추출되고 개념 노드가 형성된다.  
단번에 정해지지 않는다. 반복 입력 → 공통부 추출 → 분화 → 수렴의 과정으로 정착된다.

### 4. 언어는 출구이자 입구다

언어는 그래프 구조를 표현하는 인터페이스다.  
입력 언어는 `LangToGraph`로 그래프 주소로 변환되고,  
출력 언어는 `GraphToLang`으로 그래프 구조에서 파생된다.

---

## 컴포넌트 목록 (설계 기준)

| 컴포넌트 | 역할 | MK5 대응 |
|---|---|---|
| `LangToGraph` | 언어 → 개념 포인터 집합 | InputSegmenter + HashResolver + ActivationEngine 부분 |
| `GraphToLang` | 그래프 → 언어 | OllamaVerbalizer |
| `GraphIngestService` | EmptySlot → 신규 노드 생성 | GraphIngestService |
| `ActivationEngine` | ConceptPointer → ThoughtView | ActivationEngine |
| `ThoughtEngine` | 사고/판정/수정 | ThoughtEngine |
| `ConceptDifferentiation` | 공통부 추출 + 개념 분화 | 미구현 (MK5에서 이관) |
| `SearchSidecar` | 외부 검색 루프 | SearchSidecar |
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
  → ToolResult를 LangToGraph로 변환 후 ThoughtView에 반영
```

ThoughtEngine은 도구 실행 여부를 판단하지만, 도구 자체는 교체 가능한 외부 모듈이다.

---

## 미결 설계 결정

아래 항목은 구현 전에 확정이 필요하다.

| 항목 | 내용 |
|---|---|
| LangToGraph 내부 분해 방식 | 의미 단위 분해를 LLM으로 할지, 임베딩 클러스터링으로 할지 |
| EmptySlot 처리 시점 | LangToGraph 반환 직후 즉시 ingest할지, Activation 이후에 할지 |
| ConceptDifferentiation 임계치 | 유사도 판정 threshold 값 |
| 노드 텍스트 레이블 정책 | 레이블 없는 노드를 verbalization에서 어떻게 처리할지 |
| ThoughtEngine 도구 판단 방식 | LLM 판단인지 규칙 기반인지 (2차) |
