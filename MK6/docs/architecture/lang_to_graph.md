# LangToGraph

작성: 2026-04-20  
상태: 구현 완료 → `core/translation/lang_to_graph.py`

---

## 역할

LangToGraph는 **언어를 그래프로 번역**하는 함수다.

MK6의 인지 시스템은 그래프 도메인에서만 작동한다.  
언어는 외부 표현이다. 시스템이 언어를 처리하려면 반드시 그래프 구조로 변환되어야 한다.  
이 번역이 LangToGraph의 역할이다.

"번역"이라는 의미:
- 단순 조회(lookup)가 아니다
- 문장 안의 **개념(노드)**과 **관계(엣지)**를 모두 그래프 구조로 옮긴다
- 기존 그래프에 있는 개념이면 그 주소(ConceptPointer)를 반환
- 없는 개념이면 빈 자리(EmptySlot)를 남긴다
- **저장이 아니라 번역이다** — 저장(ingest)은 EmptySlot이 채워질 때 별도로 발생

```
LangToGraph(sentence: str) → TranslatedGraph

TranslatedGraph:
  - nodes:  list[ConceptRef]      # 문장의 모든 토큰 (필터링 없이 전체, 원래 sentence 순서)
  - edges:  list[TranslatedEdge]  # 번역된 관계들
  - source: str                   # 원문 (provenance용)

ConceptRef = ConceptPointer | EmptySlot

ConceptPointer:
  - node_id: 그래프 노드 ID
  - address_hash: 해시 주소
  - local_subgraph: 해당 노드 중심의 국소그래프 (N-hop)
  - importance: float   # centroid 기반 중요도 점수
                        # ThoughtEngine이 key_hashes/ref_hashes 분류에 사용

EmptySlot:
  - concept_hint: 번역하려 했던 의미 단위
  - unfound: True
  - importance: float   # centroid 기반 중요도 점수

TranslatedEdge:
  - source_ref: ConceptRef        # 관계의 출발 개념
  - target_ref: ConceptRef        # 관계의 도착 개념
  - edge_family: "concept" | "relation"
  - connect_type: "flow" | "neutral" | "opposite" | "conflict"
  - proposed_connect_type: str | None   # 불확실한 경우 후보 보존
  - confidence: float
```

---

## 내부 처리 순서

```
LangToGraph(sentence)
  │
  ▼
① 의미 구조 분해
  - 문장을 토큰 단위로 분해
  - 각 토큰 → ConceptPointer | EmptySlot resolve
  │
  ▼
② 각 토큰에 대해: 그래프 조회 (2패스)
  │
  1패스 — exact match:
  ├─ normalize_text(token) → words 테이블 조회
  ├─ [있음] → LocalGraphExtractor.extract(node) → ConceptPointer
  └─ [없음] → 다음 단계로
  │
  2패스 — 임베딩 유사도 (1패스 LocalSubgraph 합산이 후보 풀):
  ├─ token 임베딩 계산
  ├─ 후보 풀과 코사인 유사도 비교
  ├─ 유사도 ≥ threshold → ConceptPointer
  └─ 유사도 < threshold, 또는 후보 없음 → EmptySlot
  │
  ▼
③ 중요도 점수 할당 (_assign_importances)
  - 문장 내 모든 토큰 임베딩의 centroid 계산
  - 각 토큰의 cosine(emb, centroid) → ref.importance 에 in-place 저장
  - ConceptPointer의 WorldGraph 저장 임베딩은 사용하지 않음
    (그래프 상태가 centroid를 오염시키지 않도록)
  - 임베딩 없는 토큰: 0.5 + 0.3 × (len/max_len) 폴백
  │
  ▼
④ 모든 토큰을 nodes에 포함 (필터링 없음)
  - 인접 토큰 쌍 → neutral TranslatedEdge (양쪽 모두 2자 이상인 경우만)
  │
  ▼
반환: TranslatedGraph(nodes=[모든 ConceptRef], edges=[TranslatedEdge, ...])
```

**near/far 20% 필터링은 ThoughtEngine에서 수행한다.**  
LangToGraph는 모든 토큰을 importance 점수와 함께 넘긴다.  
ThoughtEngine이 루프 후 점수 기준으로 상위 20% → key_hashes, 하위 20% → ref_hashes로 분류한다.

---

## 호출 지점

LangToGraph는 시스템이 **언어를 받는 모든 지점**에서 호출된다.  
인지 시스템은 언어를 직접 처리하지 않는다 — 항상 이 번역을 거친다.

| 호출 지점 | 입력 | 목적 |
|---|---|---|
| 사용자 입력 처리 | 사용자 메시지 | 언어 → 그래프 번역, EmptySlot 식별 |
| 어시스턴트 응답 ingest | 어시스턴트 발화 | 출력 언어를 다시 그래프로 반영 |

검색 결과는 LangToGraph를 거치지 않는다.  
빈 DB에서 재파싱 시 EmptySlot cascade + PoolTimeout이 발생하므로, 검색 결과는 `_ingest_slot`으로 직접 노드 생성하고 `payload["search_summary"]`에 요약만 저장한다.

---

## EmptySlot의 의미와 처리

EmptySlot은 "그래프에 아직 없는 개념"의 표시다.

**LangToGraph는 EmptySlot을 마킹만 하고 그대로 반환한다. 이 시점에 검색하지 않는다.**  
검색은 Think 루프 내부에서 필요 시 발생한다.

모든 EmptySlot은 `translated.nodes`에 포함되어 TempThoughtGraph에 로드된다.  
이전에 near/far 그룹에서 누락된 EmptySlot이 검색을 트리거하지 못하는 문제가 있었으나,  
현재는 필터링 없이 전체를 넘기므로 모든 미지 개념이 검색 대상이 된다.

```
LangToGraph 반환값 예시 ("글록의 안전장치를 설명해줄래"):

TranslatedGraph {
  nodes: [
    EmptySlot(concept_hint="글록", importance=0.71),          ← 미지 → 검색 트리거
    ConceptPointer(address_hash="abc...", importance=0.85),   ← 안전장치
    EmptySlot(concept_hint="설명해줄래", importance=0.62),
    ...  ← 모든 토큰 포함
  ]
  edges: [TranslatedEdge(...), ...]
}
```

EmptySlot은 Think 루프에서 `tg.has_empty_slots()`가 True이면 검색 트리거가 된다.

---

## 토큰 분리 및 의미 그래프 조회 방식

**단계 0 — 입력 타입 분류 (전처리):**
- `InputTypeClassifier`가 입력을 `natural | code | path | url`로 분류
- `natural` → 문장 분리 → 토큰 추출 경로
- `code | path | url` → EmptySlot 단일 단위로 처리

**단계 1 — 토큰 분리 (자연어 경로):**
- 문장 분리: `_SENTENCE_SPLIT_RE` (개행 + Unicode 문장 종결 문자)
- 토큰 추출: `_TOKEN_RE` — `[A-Za-z0-9][A-Za-z0-9_+\-./#]*|[가-힣]{2,}` (한글 **2자 이상**. 1자 한글 조사·어미는 정규식 수준에서 차단)
- 정규화: 소문자 + 한국어 접미 조사 strip (한 번만, 어간 2자 미만이면 제거 안 함)

**단계 2 — words 테이블 exact match 우선 (1패스):**
- `normalize_text(token)` → `words.surface_form` 조회
- 있으면 → `address_hash` 즉시 반환 → `nodes` 테이블에서 로컬 서브그래프 추출

**단계 3 — 없으면 임베딩 기반 유사도 조회 (2패스):**
- 모든 토큰 임베딩 계산 (nomic-embed-text) — ConceptPointer/EmptySlot 구분 없이 전체
- 1패스 LocalSubgraph 합산 노드와 코사인 유사도 비교
- 유사도 ≥ threshold → ConceptPointer
- 유사도 < threshold, 또는 후보 없음 → EmptySlot

**단계 4 — 중요도 점수 할당 및 전체 노드 반환:**
- `_assign_importances(sentence_pairs, token_embs)`: 모든 토큰에 centroid 기반 중요도 in-place 할당
  - centroid = 문장 내 모든 토큰 실시간 임베딩의 평균
  - importance = cosine(token_emb, centroid)
  - WorldGraph 저장 임베딩 불사용 → 그래프 상태가 centroid에 개입 불가
- 전체 토큰을 importance 포함한 채 `nodes`에 추가 (필터링 없음)
- 인접 토큰 쌍 → `neutral` TranslatedEdge (양쪽 모두 2자 이상인 경우만)
- **near/far 20% 분류는 ThoughtEngine에서 수행**

---

## LocalGraphExtractor

ConceptPointer에 담기는 국소그래프를 추출한다.

```
LocalGraphExtractor.extract(conn, center_hash, *, hop_radius, trust_threshold) → LocalSubgraph

LocalSubgraph:
  - center_hash: 기준 노드 address_hash
  - nodes: center 노드 + N-hop 이내 활성 노드 목록
  - edges: 노드 간 엣지 목록 (is_active=True)
  - hop_radius: 실제 사용된 탐색 반경
```

**center 노드는 trust_threshold와 무관하게 항상 포함된다.** words 테이블에서 찾아낸 노드는 아직 신뢰도가 낮더라도 반드시 TempThoughtGraph에 로드되어야 Think 루프가 해당 개념을 처리할 수 있다. trust_threshold 필터는 depth≥1인 이웃 노드에만 적용된다.

TempThoughtGraph의 `load_from_translated`는 TranslatedGraph의 모든 ConceptPointer에서 LocalSubgraph를 합산한다.

---

## GraphToLang (역방향)

그래프 도메인 → 언어 도메인으로의 역번역이다.

```
GraphToLang(conclusion_view: ConclusionView) → str

내부:
  - ConclusionView의 노드/엣지 구조를 LLM에 전달
  - LLM이 구조에서 자연어 생성
  - 언어는 파생 표현 — 구조가 먼저, 단어는 나중

ConclusionView:
  - nodes: list[Node]
  - edges: list[Edge]
  - key_hashes: set[str]          # near 그룹 (importance 상위 20%) → 핵심 키워드
  - ref_hashes: set[str]          # far 그룹 (importance 하위 20%) → 참고 개념
  - search_node_hashes: set[str]  # 이번 세션에서 search_summary 설정된 노드
                                  # (이전 세션 이웃 노드 search_summary 누출 방지)
```

텍스트 레이블 없는 노드(공통부 추출로 형성된 순수 구조 노드)는 연결된 이웃 노드들의 레이블과 엣지 관계로 간접 표현된다.

---

## 노드 텍스트 레이블 정책

MK6에서 노드의 의미는 그래프 위치(구조)에 있다. 텍스트 레이블은 부속 정보다.

```
Node:
  - node_id: 식별자
  - address_hash: 해시 주소 (탐색 키)
  - labels: list[str]   # 여러 표현 가능, 비어있을 수도 있음
  - is_active: bool
  - trust_score: float
  - stability_score: float
  - payload: dict
```

- 신규 ingest 시: EmptySlot.concept_hint → labels[0]으로 임시 등록
- 공통부 추출로 형성된 상위 개념 노드는 labels가 비어있을 수 있음
- GraphToLang은 labels 없는 노드를 구조적 이웃 표현으로 대체
