# MK4 그래프 스키마

작성: 2026-04-20  
상태: 구현 완료 → `core/storage/db.py`, `core/storage/world_graph.py`

---

## 물리적 구조

단일 SQLite 파일 (`data/memory.db`) 에 세 테이블로 구성된다.  
표면형 링크 테이블과 의미 그래프 테이블이 `address_hash`로 연결되므로 같은 파일이 적합하다.

---

## 테이블

### words — 표면형 ↔ 의미 노드 후보 링크

`words`는 단어를 단일 의미 노드에 고정하는 1:1 해시테이블이 아니다.  
정규화된 표면형(`surface_form`)과 의미 그래프 노드(`nodes.address_hash`) 사이의 **후보 링크 집합**이다.

- 같은 `surface_form`은 여러 노드에 연결될 수 있다.
- 같은 노드는 여러 `surface_form`을 가질 수 있다.
- 중복은 `(surface_form, address_hash)` 쌍 기준으로만 금지한다.

```sql
CREATE TABLE words (
    word_id       TEXT PRIMARY KEY,      -- UUID
    surface_form  TEXT NOT NULL,         -- 정규화된 표면형 ("사과", "apple")
    address_hash  TEXT NOT NULL          -- → nodes.address_hash (FK)
                  REFERENCES nodes(address_hash),
    language      TEXT,                  -- 언어 코드 (ko, en, ...), nullable
    created_at    TEXT NOT NULL
);

CREATE INDEX idx_words_surface ON words(surface_form);
CREATE UNIQUE INDEX idx_words_surface_address
    ON words(surface_form, address_hash);
CREATE INDEX idx_words_address_hash ON words(address_hash);
```

**조회 흐름:**
1. 토큰 → `normalize_text(token)` → `surface_form`
2. `words` 테이블에서 `surface_form` 일치 검색
3. 있으면 → 연결된 모든 `address_hash`를 후보로 반환
4. 각 후보 노드를 조회해 active 노드만 `ConceptPointer`로 변환
5. 후보가 하나도 없으면 → EmptySlot (검색 트리거)

이 구조는 동음이의어, 번역어, 분화된 개념, 불명확한 표면형을 문자열 규칙으로 하나만 고르지 않고 그래프 후보로 남기기 위한 것이다.

---

### nodes — 의미 그래프 노드

체감된 개념이 존재하는 레이어다.  
노드의 의미는 텍스트 레이블이 아니라 그래프 구조 위치(연결, 가중치, trust)에 있다.

```sql
CREATE TABLE nodes (
    address_hash       TEXT PRIMARY KEY,   -- 탐색 키 (node_id와 통합)
    labels             TEXT NOT NULL,      -- JSON array of str, 비어있을 수 있음
    is_abstract        INTEGER NOT NULL DEFAULT 0,  -- 공통부 추출로 형성된 구조 노드
    node_kind          TEXT NOT NULL,      -- concept | relation | event | ...
    embedding          BLOB,              -- 직렬화된 float list, nullable
    trust_score        REAL NOT NULL DEFAULT 0.5,
    stability_score    REAL NOT NULL DEFAULT 0.5,
    is_active          INTEGER NOT NULL DEFAULT 1,
    formation_source   TEXT NOT NULL,     -- ingest | differentiation | search
    payload            TEXT NOT NULL DEFAULT '{}',  -- JSON
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX idx_nodes_is_active ON nodes(is_active);
CREATE INDEX idx_nodes_trust ON nodes(trust_score);
```

**is_abstract=1인 노드:**
- 공통부 추출(ConceptDifferentiation)로 생성됨
- labels가 비어있을 수 있음
- GraphToLang은 이웃 노드들의 레이블과 엣지 관계로 간접 표현

---

### edges — 의미 그래프 엣지

```sql
CREATE TABLE edges (
    edge_id                  TEXT PRIMARY KEY,   -- UUID
    source_hash              TEXT NOT NULL REFERENCES nodes(address_hash),
    target_hash              TEXT NOT NULL REFERENCES nodes(address_hash),
    edge_family              TEXT NOT NULL,      -- concept | relation
    connect_type             TEXT NOT NULL,      -- flow | neutral | opposite | conflict
    proposed_connect_type    TEXT,               -- 허용 집합 밖 제안 보존
    proposal_reason          TEXT,
    translation_confidence   REAL,              -- LangToGraph가 할당한 connect_type 신뢰도
    provenance_source        TEXT NOT NULL,     -- lang_to_graph | model_assertion | search | differentiation
    support_count            INTEGER NOT NULL DEFAULT 0,
    conflict_count           INTEGER NOT NULL DEFAULT 0,
    contradiction_pressure   REAL NOT NULL DEFAULT 0.0,
    trust_score              REAL NOT NULL DEFAULT 0.5,
    edge_weight              REAL NOT NULL DEFAULT 1.0,
    is_active                INTEGER NOT NULL DEFAULT 1,
    is_temporary             INTEGER NOT NULL DEFAULT 0,
    payload                  TEXT NOT NULL DEFAULT '{}',  -- JSON
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);

CREATE INDEX idx_edges_source ON edges(source_hash, is_active);
CREATE INDEX idx_edges_target ON edges(target_hash, is_active);
CREATE INDEX idx_edges_connect_type ON edges(connect_type);
```

---

## 입력 전처리 파이프라인

토큰 분리 전에 **입력 타입 분류기**를 먼저 통과한다.

### 입력 타입 분류기

자연어와 비자연어(코드/URL/파일 경로)를 구분해 처리 경로를 분기한다.  
**방식: 규칙 → 임베딩 폴백 (D안)**

```
입력 문자열
  │
  ▼
1단계: 정규식 규칙
  - url:    ^https?:// | ^ftp://
  - path:   (^[./\]|[/\]) + 확장자 패턴 (.py|.js|.ts|.md|.txt 등)
  - code:   들여쓰기 블록 + 코드 키워드 (def |class |function |const |import |{...})
  - 위 모두 불일치 → 2단계로

2단계: 임베딩 유사도
  - "natural language text", "source code", "file path", "url" 프로토타입 임베딩 준비
  - 입력 임베딩 → 프로토타입과 코사인 유사도 → 가장 가까운 카테고리
  - 유사도 차이 < threshold → "natural"로 폴백
```

처리 경로:
- `"natural"` → 문장 분리 → 토큰 추출 → 의미 그래프 조회
- `"code" | "path" | "url"` → 전체를 단일 단위로 임베딩 폴백

---

## 단어 분리 및 해시 방식

자연어 경로에 적용된다.

**문장 분리 — Unicode 문장 종결 문자 포함:**
```python
_SENTENCE_SPLIT_RE = re.compile(
    r"(?:\r?\n)+"
    r"|(?<=[.!?])\s+"
    r"|(?<=[。．｡])"
    r"|(?<=[！？｢｣])\s*"
    r"|(?<=[‼‽⁇⁈⁉])\s*"
    r"|(?<=[…‥])\s*"
    r"|(?<=[؟۔।॥។៕၊])\s*"
    r"|(?<=[᙮᠃᠉])\s*"
    r"|(?<=[።፧፨])\s*"
)
```

**토큰 추출:**
```python
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-./#]+|[가-힣]+")
```

**정규화:**
- 소문자 변환
- 한국어 조사 제거 (은/는/이/가/을/를/에/의/도/로 등)
- 앞뒤 공백/구두점 제거

**주소 계산:**
```python
address_hash = sha256(f"word::{normalize_text(token)}").hexdigest()[:32]
```

`compute_hash()`는 신규 EmptySlot을 노드로 ingest할 때 사용하는 주소 계산이다.  
`words.surface_form` 조회는 해시가 아니라 정규화된 표면형 자체로 수행한다.

---

## 의미 그래프 조회 방식

토큰 분리 이후 의미 그래프 노드 탐색은 2패스로 진행한다.

```
토큰
  → normalize_text(token)
  → words.surface_form exact match
      → 연결된 모든 active node를 ConceptPointer 후보로 반환
  → exact 후보가 없으면
      → 1패스 LocalSubgraph 후보 풀과 임베딩 유사도 비교
      → 유사도 ≥ threshold → ConceptPointer
      → 유사도 < threshold 또는 후보 없음 → EmptySlot
```

표면형이 여러 노드에 연결된 경우 LangToGraph는 하나를 고르지 않는다.  
모든 후보를 `TranslatedGraph.nodes`에 포함시키고, 인접 토큰 관계는 후보 조합으로 `TranslatedEdge`를 만든다.

---

## words 테이블 동기화 정책

ConceptDifferentiation이 노드를 merge하거나 differentiate할 때 words 테이블도 함께 갱신한다.

### Merge (여러 노드 → 하나)

```
병합 전:
  words: [cross → node_A], [cross → node_B], [apple → node_B]
  노드: node_B → node_A로 병합

병합 후:
  words: [cross → node_A], [apple → node_A]
```

- 병합되는 노드에 연결된 모든 표면형 링크를 생존 노드로 이전한다.
- 이미 같은 `(surface_form, survivor_hash)` 링크가 있으면 병합 대상 링크는 삭제한다.
- 병합된 노드는 비활성화한다 (`is_active=0`).

### Differentiation (하나 → 둘 이상)

```
분화 전:
  words: [십자가 → node_X], [cross → node_X]

분화 후:
  words: [십자가 → node_X1],
         [cross → node_X2]
  또는 불명확하면:
         [cross → node_X1], [cross → node_X2]
```

- 기존 단어들을 신규 노드에 배분할 수 있다.
- 배분 기준은 각 단어의 임베딩과 신규 노드 임베딩의 코사인 유사도를 사용할 수 있다.
- 배분이 불명확하면 같은 surface_form을 여러 노드에 연결한다.

---

## 관계 요약

```
words.surface_form  ↔ nodes.address_hash   (표면형 후보 링크)
edges.source_hash   → nodes.address_hash   (엣지 출발)
edges.target_hash   → nodes.address_hash   (엣지 도착)
```

