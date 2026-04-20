# MK6 아키텍처 개요

작성: 2026-04-20  
상태: 구현 완료 (MVP)

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
  │     조건: EmptySlot 존재
  │     경로: 모든 EmptySlot hint 합산 → 1회 검색 → _ingest_slot(hint, search_text)
  │           ├─ 결과를 payload["search_summary"]에 저장 → GraphToLang에서 LLM 컨텍스트로 활용
  │           └─ ingest 완료 후 co_occurrence 엣지 생성 (노드 추가 없음):
  │               ① ingest ↔ ingest (같은 쿼리에서 함께 등장한 신규 개념들 간)
  │               ② ingest ↔ ConceptPointer (신규 개념 ↔ 기존 known 개념)
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
| `SearchFunction` | EmptySlot hint 합산 → 1회 검색 → ingest + payload 저장 | SearchSidecar |
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

## 확정된 설계 결정

| 항목 | 결정 |
|---|---|
| InputTypeClassifier | 규칙 → 임베딩 폴백 혼합 (D안) |
| ConceptDifferentiation 유사도 | 복합 스코어 (C안) + 적응형 α (이웃 수 기반) |
| 토큰 중요도 필터링 | LangToGraph에서 문장별 `_split_near_far`로 **near / far 두 그룹 분리**. near(`TOKEN_IMPORTANCE_NEAR_RATIO=20%`): centroid 근접, 문장 대표 개념 → 핵심 키워드. far(`TOKEN_IMPORTANCE_FAR_RATIO=20%`): centroid 원거리, 고유명사·도메인 특이 개념 → 참고 개념. near 우선(겹치면 near 귀속). near 최소 1개 보장. 임베딩 없는 경우 레이블 길이 폴백. |
| EmptySlot 검색 전략 | `user_input` 원문으로 1회 검색 (없으면 hint 합산 폴백). LangToGraph 재파싱 없음 → ingest + payload 저장. search_fn 전체에 `asyncio.wait_for(SEARCH_TIMEOUT=20s)` 적용. |
| 검색 결과 활용 방식 | `payload["search_summary"]`에 저장 (최대 800자). GraphToLang이 `[검색 컨텍스트]` 섹션으로 LLM에 주입. |
| 검색 ingest 노드 간 엣지 | `_fill_empty_slots` 완료 후 co_occurrence 엣지 생성 (노드 추가 없음). ① ingest↔ingest: 같은 쿼리 내 신규 개념들 간. ② ingest↔ConceptPointer(`concept_hashes`=key∪ref 기준). 상한 없음 (업스트림 토큰 필터로 노드 수가 이미 제한됨). |
| ThoughtEngine 인터페이스 | `lang_to_graph_fn` 파라미터 제거. 검색 결과를 재번역하지 않으므로 불필요 |
| GraphToLang 핵심/참고 분류 | `known_hashes` 폐기. **`key_hashes`(near 그룹) / `ref_hashes`(far 그룹)** 기반으로 교체. 분류 기준은 언어 구조(centroid 거리)이며 그래프 상태와 무관. EmptySlot에서 생성된 노드도 near/far 그룹 기준으로 분류. |
| GraphToLang 근거 연결 포맷 | `→[connect_type, weight]→` 형식. edge_weight를 포함해 LLM이 연결 강도를 참고할 수 있도록 함. |
| abstract 노드 GraphToLang 출력 | 완전 제외. 핵심/참고 키워드 및 근거 연결 양쪽 모두에서 필터링 |
| ConceptDifferentiation 후보 조건 | stability_score > COMMIT_STABILITY_WEAK 추가. 신규 ingest 노드(stability=0.1)는 개념 경계 미정착 상태이므로 분화 제외 |
| WAL 체크포인트 | `close_db()`에서 `PRAGMA wal_checkpoint(TRUNCATE)` 실행 후 커넥션 종료. server.py에 SIGINT/SIGTERM 핸들러 추가 (이중 Ctrl+C 등 비정상 종료 대비). |

---

## Think 루프 수렴 판단

수치 기반이 아닌 **구조적 변화 감지** 방식으로 판단한다.

수렴 조건 (둘 중 하나 충족 시 루프 종료):
- **그래프 수정 없음**: 이번 루프 회차에서 임시 사고 그래프에 수정된 노드/엣지가 없다
- **개선점 없음**: 수정을 시도했으나 목표 노드에 연결된 입력 의도 대비 유의미한 변화가 없다

수렴하지 않으면 루프를 계속한다. 최대 루프 횟수는 안전장치로 설정값(`THINK_MAX_LOOPS`)으로 유지한다.

---

## 세계그래프 커밋 판단 기준

임시 사고 그래프의 결과를 세계그래프에 반영할 때, 업데이트 종류에 따라 강도를 달리한다.

| 상황 | 반영 강도 | 처리 방식 |
|---|---|---|
| 일반적 상황에 대응 가능한 업데이트 (특수 상황 아님) | **강** | 정상 trust/stability로 커밋 |
| 기존 세계그래프와 충돌하는 결론 | **강** | 기존 노드/엣지의 trust·stability 하향 |
| 새로운 연결 (기존에 없던 edge) | **강** | 정상 trust로 edge 추가 |
| 그 외 일반적 업데이트 | **약** | 매우 낮은 trust/stability로 일단 연결 추가 |

"약한 커밋"은 세계그래프를 오염시키지 않으면서 나중에 같은 연결이 반복되면 자연스럽게 강화되도록 한다.  
특수 상황에서 나온 결론은 일반화하지 않는다 — 약한 trust로만 기록.

---

## 미결 설계 결정

| 항목 | 내용 |
|---|---|
| ThoughtEngine 도구 판단 방식 | FileReader/CodeEditor 사용 시점 판단 — LLM인지 규칙인지 (2차) |

---

## 구현 상태

| 컴포넌트 | 파일 | 상태 |
|---|---|---|
| `InputTypeClassifier` | `core/translation/input_classifier.py` | ✅ 완료 |
| `TokenSplitter` | `core/translation/token_splitter.py` | ✅ 완료 |
| `LangToGraph` | `core/translation/lang_to_graph.py` | ✅ 완료 |
| `HashResolver` | `core/utils/hash_resolver.py` | ✅ 완료 |
| `LocalGraphExtractor` | `core/utils/local_graph_extractor.py` | ✅ 완료 |
| `TempThoughtGraph` | `core/thinking/temp_thought_graph.py` | ✅ 완료 |
| `ConceptDifferentiation` | `core/thinking/concept_differentiation.py` | ✅ 완료 |
| `ThoughtEngine` | `core/thinking/thought_engine.py` | ✅ 완료 |
| `WorldGraph` (Storage) | `core/storage/world_graph.py` | ✅ 완료 |
| `GraphToLang` | `app/pipeline.py` (내부 함수) | ✅ 완료 (LLM 위임) |
| `Pipeline` | `app/pipeline.py` | ✅ 완료 |
| `FastAPI Server` | `app/server.py` | ✅ 완료 |
| `SearchFunction` | `tools/search_client.py` | ✅ 완료 (DuckDuckGo + Wikipedia KO/EN) |
| `ToolLayer` | 미구현 | 🔲 2차 |
