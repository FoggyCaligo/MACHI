# MK6 그래프 스키마

작성: 2026-04-20  
상태: 설계 단계

---

## 물리적 구조

단일 SQLite 파일 (`data/memory.db`) 에 세 테이블로 구성된다.  
단어 테이블과 의미 그래프 테이블이 `address_hash`로 연결되므로 같은 파일이 적합하다.

---

## 테이블

### words — 단어 해시테이블

단어 → 의미 그래프 노드로의 조회 테이블이다.  
그래프라기보다 해시테이블에 가깝다. 단어가 "단어 연결 Edge"로 의미 그래프 노드에 연결되는 구조다.

```sql
CREATE TABLE words (
    word_id       TEXT PRIMARY KEY,      -- UUID
    surface_form  TEXT NOT NULL,         -- 원형 단어 ("사과", "apple")
    address_hash  TEXT NOT NULL          -- → nodes.address_hash (FK)
                  REFERENCES nodes(address_hash),
    language      TEXT,                  -- 언어 코드 (ko, en, ...), nullable
    created_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_words_surface ON words(surface_form);
CREATE INDEX idx_words_address_hash ON words(address_hash);
```

**조회 흐름:**
1. 토큰 → `normalize_text(token)` → `sha256` → `surface_hash`
2. `words` 테이블에서 `surface_form` 일치 검색
3. 있으면 → `address_hash` 반환 (의미 그래프 노드 주소)
4. 없으면 → EmptySlot (검색 트리거)

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

```
입력 문자열
  │
  ▼
InputTypeClassifier.classify(text) → "natural" | "code" | "path" | "url"

판정 기준 (규칙 기반, MVP):
  - url:  http:// / https:// / ftp:// 로 시작
  - path: 경로 구분자 패턴 (/, \, ./ , ../) + 확장자 패턴
  - code: 들여쓰기 블록, def/class/function/{}/[] 등 코드 구조 패턴
  - natural: 위 어느 것도 아니면 자연어

처리 경로:
  - "natural" → 문장 분리 → 토큰 추출 → 의미 그래프 조회
  - "code" | "path" | "url" → 전체를 단일 단위로 묶어 임베딩 폴백
```

비자연어 입력은 전체를 하나의 단위로 임베딩에 넘긴다.  
이후 코드/파일 도구 레이어(2차)가 붙으면 해당 경로가 확장된다.

---

## 단어 분리 및 해시 방식

자연어 경로에 적용된다.

**문장 분리 — Unicode 문장 종결 문자 포함:**
```python
_SENTENCE_SPLIT_RE = re.compile(
    r"(?:\r?\n)+"                        # 개행
    r"|(?<=[.!?])\s+"                    # 기본 영어 종결
    r"|(?<=[。．｡])"                     # CJK 마침표
    r"|(?<=[！？｢｣])\s*"                # 전각 느낌표/물음표
    r"|(?<=[‼‽⁇⁈⁉])\s*"               # 복합 구두점
    r"|(?<=[…‥])\s*"                    # 말줄임표
    r"|(?<=[؟۔।॥។៕၊])\s*"            # 아랍/인도/동남아
    r"|(?<=[᙮᠃᠉])\s*"                 # 캐나다 음절/몽골
    r"|(?<=[።፧፨])\s*"                  # 에티오피아
)
```

**토큰 추출 — 한글 1자 이상으로 수정:**
```python
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-./#]+|[가-힣]+")
```

**정규화:**
- 소문자 변환
- 한국어 조사 제거 (은/는/이/가/을/를/에/의/도/로 등)
- 앞뒤 공백/구두점 제거

**해시 계산:**
```python
address_hash = sha256(f"word::{normalize_text(token)}").hexdigest()[:32]
```

scope prefix를 `"word::"`로 고정해 의미 그래프 노드 해시와 충돌을 방지한다.

---

## 의미 그래프 조회 방식

토큰 분리 이후 의미 그래프 노드 탐색은 **임베딩 기반 유사도**로 진행한다.  
(MK5 SearchScopeGate의 nomic-embed-text 방식과 동일)

```
토큰 → embedding 계산 (nomic-embed-text)
     → nodes 테이블에서 코사인 유사도 상위 N개 후보 검색
     → 유사도 ≥ threshold → ConceptPointer 반환
     → 유사도 < threshold → EmptySlot
```

`words` 테이블이 exact match를 담당하고, 임베딩은 exact match 실패 시 또는 의미 확인용으로 사용한다.

---

## 관계 요약

```
words.address_hash → nodes.address_hash   (단어 → 의미 노드)
edges.source_hash  → nodes.address_hash   (엣지 출발)
edges.target_hash  → nodes.address_hash   (엣지 도착)
```
