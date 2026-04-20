# MK6 파일 구조 및 컴포넌트

작성: 2026-04-20  
상태: 구현 완료 (MVP)

---

## 디렉터리 트리

```
MK6/
├── __init__.py                      # 패키지 루트
├── config.py                        # 전역 설정 (환경변수 기반)
├── requirements.txt                 # 의존성 목록
├── pytest.ini                       # 테스트 설정
├── run_cli.py                       # 대화형 CLI 실행 스크립트
├── run_server.py                    # FastAPI 서버 실행 스크립트
│
├── core/                            # 인지 시스템 핵심 레이어
│   ├── entities/                    # 데이터 구조 (dataclass)
│   │   ├── node.py
│   │   ├── edge.py
│   │   ├── word_entry.py
│   │   └── translated_graph.py
│   │
│   ├── storage/                     # WorldGraph 영구 저장소
│   │   ├── db.py
│   │   └── world_graph.py
│   │
│   ├── utils/                       # 독립 유틸리티
│   │   ├── hash_resolver.py
│   │   └── local_graph_extractor.py
│   │
│   ├── translation/                 # 언어 → 그래프 번역 레이어
│   │   ├── input_classifier.py
│   │   ├── token_splitter.py
│   │   └── lang_to_graph.py
│   │
│   └── thinking/                    # Think 루프 / 개념 형성 레이어
│       ├── temp_thought_graph.py
│       ├── concept_differentiation.py
│       └── thought_engine.py
│
├── tools/                           # 외부 서비스 클라이언트
│   ├── ollama_client.py
│   └── search_client.py
│
├── app/                             # 파이프라인 진입점 / API
│   ├── pipeline.py
│   └── server.py
│
├── tests/                           # 단위 테스트
│   ├── test_hash_resolver.py
│   ├── test_token_splitter.py
│   ├── test_storage.py
│   ├── test_concept_differentiation.py
│   └── test_temp_thought_graph.py
│
└── docs/
    └── architecture/
        ├── MK6_overview.md          # 전체 아키텍처 개요
        ├── file_structure.md        # 이 문서
        ├── lang_to_graph.md         # LangToGraph 상세 설계
        ├── graph_schema.md          # SQLite 스키마 및 전처리 파이프라인
        └── concept_differentiation.md  # 개념 분화 알고리즘
```

---

## config.py — 전역 설정

모든 조정 가능한 수치와 경로를 한 곳에 모은다. 환경변수 우선, 없으면 기본값 사용.

| 설정값 | 기본값 | 설명 |
|---|---|---|
| `DB_PATH` | `data/memory.db` | SQLite DB 파일 경로 |
| `EMBEDDING_MODEL_NAME` | `nomic-embed-text` | Ollama 임베딩 모델 |
| `EMBEDDING_TIMEOUT_SECONDS` | `10.0` | 임베딩 요청 타임아웃 |
| `LANG_TO_GRAPH_SIMILARITY_THRESHOLD` | `0.75` | 임베딩 유사도 임계치 (ConceptPointer 확정) |
| `LANG_TO_GRAPH_MAX_EMBEDDING_NODES` | `200` | 유사도 비교 후보 노드 최대 수 |
| `TOKEN_IMPORTANCE_NEAR_RATIO` | `0.15` | centroid 근접 토큰 비율 (문장 대표 개념 포착) |
| `TOKEN_IMPORTANCE_FAR_RATIO` | `0.15` | centroid 원거리 토큰 비율 (고유명사·도메인 특이 개념 포착) |
| `TOKEN_IMPORTANCE_MIN` | `1` | 중요도 필터 후 보장하는 최소 토큰 수 (극단적으로 짧은 문장 대비) |
| `GRAPH_TO_LANG_EDGE_RATIO` | `0.30` | GraphToLang에 포함할 엣지 비율. 정렬 후 상위 30%만 LLM 컨텍스트에 전달 (pairwise O(n²) 폭발 방지) |
| `LOCAL_GRAPH_N_HOP` | `2` | 국소 그래프 탐색 반경 |
| `LOCAL_GRAPH_TRUST_THRESHOLD` | `0.2` | 국소 그래프 포함 최소 trust_score |
| `INPUT_CLASSIFIER_EMBED_THRESHOLD` | `0.70` | 입력 타입 분류 임베딩 신뢰 임계치 |
| `DIFFERENTIATION_THRESHOLD` | `0.80` | 개념 분화 유사 쌍 탐지 임계치 |
| `DIFFERENTIATION_MIN_NEIGHBORS` | `3` | α 조정 시작 최소 이웃 수 |
| `DIFFERENTIATION_MIN_ALPHA` | `0.3` | 임베딩 최소 반영 비율 |
| `DIFFERENTIATION_ALPHA_DECAY_RATE` | `10.0` | α 감소율 (이웃 수 기준) |
| `THINK_MAX_LOOPS` | `10` | Think 루프 최대 횟수 (안전장치) |
| `COMMIT_TRUST_STRONG` | `0.7` | 강한 커밋 trust_score |
| `COMMIT_TRUST_WEAK` | `0.15` | 약한 커밋 trust_score |
| `COMMIT_STABILITY_STRONG` | `0.6` | 강한 커밋 stability_score |
| `COMMIT_STABILITY_WEAK` | `0.1` | 약한 커밋 stability_score |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_TIMEOUT_SECONDS` | `600.0` | Ollama 생성 요청 타임아웃 |
| `OLLAMA_MODEL_NAME` | `` (필수 설정) | 텍스트 생성 모델 이름 |
| `OLLAMA_NUM_PREDICT` | `512` | GraphToLang 최대 생성 토큰 수 |

---

## core/entities/

시스템 전체가 공유하는 데이터 구조. 순수 dataclass이며 외부 의존성 없음.

### node.py — `Node`

세계그래프(WorldGraph)의 노드 하나를 표현한다. 의미는 텍스트 레이블이 아니라 그래프 구조 위치에 있다.

```
address_hash     str          PK (탐색 키, node_id와 통합)
node_kind        NodeKind     concept | relation | event | goal
formation_source FormationSource  ingest | differentiation | search
labels           list[str]    텍스트 레이블 (비어있을 수 있음, 추상 노드)
is_abstract      bool         공통부 추출로 형성된 구조 노드
trust_score      float        신뢰도 (0~1)
stability_score  float        안정도 (0~1)
embedding        list[float]  임베딩 벡터 (nullable)
payload          dict         확장 데이터
```

헬퍼: `labels_json()`, `payload_json()`, `labels_from_json()`, `payload_from_json()`, `primary_label()`, `touch()`

### edge.py — `Edge`

노드 간 의미 연결 하나를 표현한다.

```
edge_id                str          UUID PK
source_hash / target_hash  str      → nodes.address_hash
edge_family            EdgeFamily   concept | relation
connect_type           ConnectType  flow | neutral | opposite | conflict
proposed_connect_type  str | None   허용 집합 밖 후보 보존
provenance_source      ProvenanceSource  lang_to_graph | model_assertion | search | differentiation
support_count / conflict_count  int  지지/충돌 횟수
contradiction_pressure float        모순 압력
trust_score / edge_weight  float    신뢰도 / 가중치
is_active / is_temporary   bool     활성 여부 / 임시 여부
```

### word_entry.py — `WordEntry`

단어(surface_form) → 의미 그래프 노드(address_hash) 매핑. words 테이블 한 행.

```
word_id       str          UUID PK
surface_form  str          원형 단어 ("사과", "apple")
address_hash  str          → nodes.address_hash
language      str | None   언어 코드 (ko, en, …)
```

### translated_graph.py — `LocalSubgraph`, `ConceptPointer`, `EmptySlot`, `TranslatedEdge`, `TranslatedGraph`

LangToGraph의 입출력 구조.

```
LocalSubgraph      N-hop 국소 그래프 (center_hash, nodes, edges, hop_radius)
ConceptPointer     그래프에서 찾은 개념 참조 (address_hash + local_subgraph)
EmptySlot          찾지 못한 개념 자리 (concept_hint, unfound=True)
ConceptRef         ConceptPointer | EmptySlot
TranslatedEdge     번역된 관계 (source_ref, target_ref, edge_family, connect_type, confidence)
TranslatedGraph    번역 결과 전체 (nodes, edges, source)
```

---

## core/storage/

WorldGraph 영구 저장소. SQLite 기반.

### db.py — `open_db`, `close_db`

SQLite 커넥션을 열고 스키마(DDL)를 초기화한다.

- `open_db(db_path: str) → sqlite3.Connection`
  - 부모 디렉터리 자동 생성, `row_factory=sqlite3.Row`, WAL 모드, FK 활성화
  - DDL: `words`, `nodes`, `edges` 테이블 + 인덱스 (`CREATE TABLE IF NOT EXISTS`)
- `close_db(conn: sqlite3.Connection) → None`
  - `PRAGMA wal_checkpoint(TRUNCATE)` 실행 후 커넥션 종료
  - WAL 파일을 메인 DB에 병합하고 0바이트로 초기화한다
  - 체크포인트 실패 시에도 `conn.close()`는 반드시 실행 (Ctrl+C 안전 종료)

### world_graph.py — 노드/엣지/단어 CRUD

WorldGraph에 대한 모든 읽기/쓰기 함수. 트랜잭션은 호출자가 관리한다.

| 함수 | 설명 |
|---|---|
| `insert_node` / `get_node` / `update_node` | 노드 삽입/조회/수정 |
| `deactivate_node` | `is_active=0`으로 소프트 삭제 |
| `get_active_nodes` | 활성 노드 전체 조회 |
| `insert_edge` / `get_edge` / `update_edge` | 엣지 삽입/조회/수정 |
| `get_edges_for_node` | 특정 노드에 연결된 엣지 조회 (출발/도착 양방향) |
| `insert_word` / `get_word` | 단어 삽입/조회 (surface_form 기준) |
| `get_words_for_node` | 특정 노드에 연결된 단어 목록 |
| `remap_words_to_node` | Merge 시 여러 노드의 단어를 하나로 일괄 재연결 |

임베딩은 `struct.pack/unpack`으로 BLOB 직렬화.

---

## core/utils/

독립 유틸리티. 외부 상태 없음. 다른 레이어에서 자유롭게 호출 가능.

### hash_resolver.py — `normalize_text`, `compute_hash`

토큰 → address_hash 변환.

- `normalize_text(token)` — NFC 정규화 → 소문자 → 앞뒤 구두점 제거 → 한국어 조사 제거 (단독 조사 토큰은 유지)
- `compute_hash(token)` — `sha256("word::" + normalize_text(token)).hexdigest()[:32]`
- scope prefix `"word::"` 로 의미 그래프 노드 해시와 충돌 방지

### local_graph_extractor.py — `extract`

특정 노드를 중심으로 N-hop 이내 국소 그래프를 BFS로 추출한다.

- `extract(conn, center_hash, *, hop_radius, trust_threshold) → LocalSubgraph`
- **center 노드(depth=0)는 trust threshold와 무관하게 항상 포함** — words 테이블로 찾은 노드가 신뢰도와 관계없이 그래프에 로드되어야 하기 때문
- 이웃 노드(depth≥1)는 `trust_score < trust_threshold`이면 포함하지 않음
- `is_active=False` 노드/엣지 제외

---

## core/translation/

언어 → 그래프 번역 레이어. "번역"이며 저장(ingest)이 아니다.

### input_classifier.py — `classify`

입력 문자열의 타입을 `natural | code | path | url`로 분류한다.

- **1단계 (규칙)**: URL 정규식, 파일 경로 패턴, 코드 키워드+들여쓰기 감지
- **2단계 (임베딩 폴백)**: 규칙이 모호하면 프로토타입 임베딩과 코사인 유사도 비교
- 유사도 차이 < threshold → 안전 폴백 `"natural"`

### token_splitter.py — `split_sentences`, `extract_tokens`, `tokenize`

자연어 텍스트를 문장 → 토큰으로 분리한다.

- `_SENTENCE_SPLIT_RE` — 개행 + Unicode 문장 종결 문자 (영문/CJK/아랍/인도/동남아/에티오피아)
- `_TOKEN_RE = r"[A-Za-z0-9][A-Za-z0-9_+\-./#]*|[가-힣]+"` — 한글 1자도 토큰 (조사 포함). 영숫자 시작을 요구하여 단독 구두점("." 등)을 토큰에서 제외.
- `tokenize(text) → list[list[str]]` — 문장별 토큰 목록

### lang_to_graph.py — `translate`

언어 입력 하나를 `TranslatedGraph`로 번역한다.

```
translate(text, conn, embed_fn) → TranslatedGraph
```

처리 흐름:
1. `classify` — 입력 타입 판정
2. 비자연어 → 전체를 단일 단위로 임베딩 조회
3. 자연어 → `tokenize` → 토큰별:
   - words 테이블 exact match → ConceptPointer
   - 실패 시 임베딩 유사도 (상위 N개 후보 풀) → ConceptPointer 또는 EmptySlot
4. **토큰 중요도 필터링** (`_filter_top_ratio`): 문장별로 **near + far 방식** 적용
   - `_importance_scores`: 문장 centroid 임베딩과의 cosine 유사도. 임베딩 없는 토큰은 레이블 길이 기반 폴백.
   - **near** (`TOKEN_IMPORTANCE_NEAR_RATIO=0.15`): centroid 근접 토큰 — 문장의 대표/중심 개념
   - **far** (`TOKEN_IMPORTANCE_FAR_RATIO=0.15`): centroid 원거리 토큰 — 고유명사·도메인 특이 개념 (cosine 유사도가 낮아 단순 상위 N% 방식에서 탈락하던 중요 개념 포착)
   - 두 그룹의 합집합을 선택. 최소 `TOKEN_IMPORTANCE_MIN(2)`개 보장.
   - **이 필터가 전체 파이프라인의 유일한 노이즈 제어 포인트**. 하위 컴포넌트(ThoughtEngine, GraphToLang)는 별도 상한을 두지 않는다.
5. 필터된 토큰만 노드로 추가. 인접 필터 통과 쌍 → `neutral` TranslatedEdge (관계 타입 확정은 ThoughtEngine)

---

## core/thinking/

Think 루프와 개념 형성 레이어.

### temp_thought_graph.py — `TempThoughtGraph`, `GraphDelta`

Think 루프 동안 메모리 상에만 존재하는 임시 사고 그래프.

- `load_from_translated(tg)` — TranslatedGraph의 ConceptPointer들에서 LocalSubgraph 로드
- `set_goal_node(node)` / `connect_to_goal(concept_hash)` — 목표 노드 설정 및 임시 연결
- `add_node` / `update_node` / `get_node` / `all_nodes`
- `add_edge` / `remove_edge` / `get_edges_for_node` / `all_edges`
- `fill_slot(slot, node)` — EmptySlot을 실제 노드로 대체
- `neighbor_hashes(hash)` — 이웃 노드 hash 집합
- `current_delta() / reset_delta()` — 루프 회차별 변경 추적 (`GraphDelta`)

`GraphDelta`: `added_nodes`, `modified_nodes`, `added_edges`, `removed_edges` — `is_empty()`로 수렴 판단에 사용.

### concept_differentiation.py — `run`, `composite_score`

임시 사고 그래프 내 유사 개념 쌍을 탐지하고 공통 추상 노드를 생성한다.

```
score = α × cosine_sim(emb_A, emb_B) + (1-α) × overlap_ratio(neighbors_A, neighbors_B)
```

α 결정:
- 이웃 수 < `MIN_NEIGHBORS` → α = 1.0 (임베딩만)
- 이웃 수 ≥ `MIN_NEIGHBORS` → α = max(`MIN_ALPHA`, 1.0 - 이웃수/`ALPHA_DECAY_RATE`)

`score ≥ DIFFERENTIATION_THRESHOLD`인 쌍 → 두 임베딩의 centroid로 추상 노드 생성 (`is_abstract=True`, `labels=[]`).

`run(tg) → list[DifferentiationResult]` — 결과를 TempThoughtGraph에 즉시 반영하고 목록을 반환.

### thought_engine.py — `ThoughtEngine`, `ConclusionView`

Think 루프 실행기.

```python
engine = ThoughtEngine(conn, embed_fn, search_fn, goal_node)
conclusion = await engine.think(translated_graph)
```

루프 한 회차:
1. EmptySlot → `user_input` 원문으로 1회 검색 → `_ingest_slot(slot, search_text)` → 노드 생성 + payload 저장
2. `concept_differentiation.run(tg)` → 분화 결과 약한 커밋
3. 수렴 판단: `delta.is_empty()` OR 노드/엣지 수 변화 없음 → 종료

EmptySlot 처리 원칙:
- 슬롯마다 개별 검색하지 않는다. `user_input` 원문을 검색 쿼리로 사용한다 (없으면 hint 합산 폴백).
  개별 토큰 합산보다 원문이 의미 있는 검색 결과를 돌려준다.
- 검색 결과를 `lang_to_graph`로 재파싱하지 않는다 (빈 DB에서 cascade 발생, PoolTimeout 위험).
- 대신 `_ingest_slot`으로 hint당 노드를 직접 생성하고 검색 결과를 `payload["search_summary"]`에 저장한다.
- 기존 노드에 요약이 없으면 `update_node`로 payload 보강한다.
- `GraphToLang`이 payload를 `[검색 컨텍스트]` 섹션으로 LLM에 주입한다 (단, known_hashes 노드 제외 — 이전 세션 오염 방지).

co_occurrence 엣지 생성:
- `_fill_empty_slots` 완료 후, 같은 쿼리에서 등장한 ingest 노드들 간 엣지 생성.
- ① **ingest ↔ ingest**: `provenance_source="search"`, `proposed_connect_type="co_occurrence"`, `is_temporary=False`
- ② **ingest ↔ ConceptPointer** (known_hashes 기준): 신규 개념이 기존 개념과 연결되어 근거 연결에 함께 표시됨.
- 상한 없음 — LangToGraph의 near+far 토큰 필터(각 15%)로 노드 수가 이미 제어되어 있음.

known_hashes 수집:
- `think()` 시작 시 `translated.nodes`에서 ConceptPointer 노드의 hash를 수집한다.
- 이 시점에 DB에 이미 존재하던 개념 = "AI가 알고 있던 개념".
- `ConclusionView.known_hashes`로 전달되어 `GraphToLang`의 핵심/참고 분류 기준이 된다.

루프 종료 후: 강한 커밋 (신규 비임시 노드/엣지 → WorldGraph).

수렴 유형:
- **강**: 일반 상황 업데이트, 새 연결, 충돌 처리 → `COMMIT_TRUST_STRONG` / `COMMIT_STABILITY_STRONG`
- **약**: 추상 노드, 불확실 업데이트 → `COMMIT_TRUST_WEAK` / `COMMIT_STABILITY_WEAK`

커밋 중복 방지: `_commit_edge`는 `get_edge`로 존재 여부를 확인한 뒤 없으면 `insert_edge`, 있으면 `update_edge`를 실행한다.

`ConclusionView` 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `nodes` | `list[Node]` | TempThoughtGraph의 전체 노드 |
| `edges` | `list[Edge]` | TempThoughtGraph의 전체 엣지 |
| `goal_hash` | `str \| None` | 목표 노드 hash |
| `had_empty_slots` | `bool` | think() 시작 시 EmptySlot 존재 여부 |
| `loop_count` | `int` | 실제 루프 횟수 |
| `model` | `str \| None` | 사용할 생성 모델 |
| `user_input` | `str \| None` | 원래 사용자 입력 (GraphToLang user 메시지) |
| `known_hashes` | `set[str]` | think() 시작 시 이미 DB에 존재하던 ConceptPointer 노드 hash 집합 |

---

## tools/

외부 서비스 클라이언트. 비동기(async/httpx).

### ollama_client.py — `get_embedding`, `generate`, `list_models`

| 함수 | 엔드포인트 | 설명 |
|---|---|---|
| `get_embedding(text)` | `POST /api/embeddings` | nomic-embed-text 임베딩 벡터 반환 |
| `generate(prompt, model)` | `POST /api/generate` | 텍스트 생성 (non-streaming). `model=None`이면 `config.OLLAMA_MODEL_NAME` 사용 |
| `list_models()` | `GET /api/tags` | 텍스트 생성 가능 모델 목록 반환. Ollama의 `details.families` 메타데이터로 임베딩 전용 모델(`nomic-bert`, `bert`, `clip` 패밀리) 제외 |

`generate`는 모델명 미설정 시 `ValueError` 발생.

### search_client.py — `search`

DuckDuckGo + Wikipedia(한국어·영어) 병렬 검색.

```python
async def search(query: str) -> str | None
```

- DuckDuckGo: `asyncio.to_thread`로 동기 라이브러리를 비동기 실행
- Wikipedia: `/w/api.php` 제목 검색 → `/api/rest_v1/page/summary/{title}` 병렬 fetch
- 세 소스를 `asyncio.gather`로 동시 실행 후 결과 합산
- 최대 `_MAX_TEXT_LEN = 2500` 자로 절삭
- 모든 소스에서 결과 없으면 `None` 반환

ThoughtEngine의 `search_fn` 시그니처(`async (query) → str | None`)를 그대로 구현한다.

---

## app/

파이프라인 진입점 및 HTTP API.

### pipeline.py — `Pipeline`, `PipelineResult`, `graph_to_lang`

전체 파이프라인을 엮는 최상위 오케스트레이터.

```python
pipeline = Pipeline(db_path=None)   # None이면 config.DB_PATH 사용
result = await pipeline.run("사과는 과일이야")
# result.response_text  : str
# result.conclusion     : ConclusionView
```

내부 구성:
- `_get_or_create_goal_node` — WorldGraph에서 고정 목표 노드 로드 또는 최초 생성
- `_search` — 검색 함수 stub (향후 교체)
- `graph_to_lang(conclusion)` — ConclusionView → 프롬프트 직렬화 → `chat()` → 언어 출력
  - 핵심 키워드: `known_hashes` 소속 노드 (abstract 제외)
  - 참고 개념: 신규 ingest 노드 (abstract 제외)
  - 근거 연결: `→[connect_type, weight]→` 포맷. `is_temporary=True` 및 abstract 엔드포인트 엣지 제외. 정렬: non-neutral 먼저 > edge_weight 내림차순 > search 외 provenance 먼저. **정렬 후 상위 `GRAPH_TO_LANG_EDGE_RATIO(30%)`만 포함** (pairwise O(n²) 폭발 방지).
  - 검색 컨텍스트: ingest 노드의 `payload["search_summary"]`만 포함 (known_hashes 제외)
- `Pipeline.close()` — `close_db()` 호출 (WAL 체크포인트 포함)

context manager 지원: `async with Pipeline() as p: ...`

### server.py — FastAPI 앱

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/health` | GET | 서버 상태 및 기본 모델명 확인 |
| `/models` | GET | Ollama 생성 모델 목록 및 현재 기본 모델 반환 |
| `/chat` | POST | `{"message": "...", "model": null}` → 언어 응답 + 메타데이터 |
| `/graph/node/{address_hash}` | GET | 노드 상세 정보 + 연결된 단어 목록 |
| `/graph/neighbors/{address_hash}` | GET | 이웃 노드 목록 + 연결 방향/타입 |

`/chat` 응답: `response`, `loop_count`, `had_empty_slots`, `node_count`, `edge_count`, `model_used`

`lifespan`으로 `Pipeline` 초기화/종료 관리. `/chat` 엔드포인트는 내부 예외를 HTTP 500으로 변환하며 서버 로그에 전체 traceback을 출력한다.

SIGINT/SIGTERM 핸들러(`_shutdown_handler`) 등록: uvicorn lifespan이 미처 실행되지 않고 프로세스가 종료되는 경우(이중 Ctrl+C, kill 명령어)에도 `Pipeline.close()` → WAL 체크포인트가 보장된다. 핸들러 실행 후 기본 동작으로 복구하여 시그널을 재전달, 프로세스를 정상 종료시킨다.

---

## 실행 스크립트

### run_cli.py

대화형 CLI. sys.path 자동 조정으로 어느 위치에서 실행해도 동작한다.

```bash
python MK6/run_cli.py          # MACHI/ 에서
python run_cli.py              # MK6/ 안에서
```

### run_server.py

FastAPI 서버 실행기.

```bash
python MK6/run_server.py [--host 127.0.0.1] [--port 8000] [--reload]
```

---

## tests/

Ollama 없이 실행 가능한 단위 테스트. in-memory SQLite 사용.

| 파일 | 테스트 대상 |
|---|---|
| `test_hash_resolver.py` | 정규화, 조사 제거, sha256 해시 일관성, scope 충돌 방지 |
| `test_token_splitter.py` | 문장 분리, 1자 한글 토큰, 영문/혼합, 특수문자 제외 |
| `test_storage.py` | 노드/엣지/단어 CRUD, 임베딩 BLOB 직렬화, remap_words_to_node |
| `test_concept_differentiation.py` | 유사도 점수, 분화 탐지, 목표 노드 제외, 추상 노드 생성 |
| `test_temp_thought_graph.py` | 노드/엣지 조작, delta 추적, EmptySlot, load_from_translated |

```bash
# MK6/ 안에서
pytest

# MACHI/ 에서
pytest MK6/
```

---

## 의존 관계 요약

```
app/pipeline.py
  ├── core/translation/lang_to_graph.py
  │     ├── core/utils/hash_resolver.py
  │     ├── core/utils/local_graph_extractor.py
  │     ├── core/storage/world_graph.py
  │     └── core/translation/input_classifier.py, token_splitter.py
  ├── core/thinking/thought_engine.py
  │     ├── core/thinking/temp_thought_graph.py
  │     ├── core/thinking/concept_differentiation.py
  │     └── core/storage/world_graph.py
  └── tools/ollama_client.py

core/storage/world_graph.py
  ├── core/entities/ (Node, Edge, WordEntry)
  └── core/storage/db.py

app/server.py
  └── app/pipeline.py
```
