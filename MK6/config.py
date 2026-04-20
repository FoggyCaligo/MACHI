from __future__ import annotations

import os


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


# ── DB ──────────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("MK6_DB_PATH", "data/memory.db")

# ── 임베딩 ───────────────────────────────────────────────────────────────────
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "nomic-embed-text").strip()
EMBEDDING_TIMEOUT_SECONDS = _env_float("EMBEDDING_TIMEOUT_SECONDS", 10.0)

# ── LangToGraph ──────────────────────────────────────────────────────────────
LANG_TO_GRAPH_SIMILARITY_THRESHOLD = _env_float("LANG_TO_GRAPH_SIMILARITY_THRESHOLD", 0.75)
LANG_TO_GRAPH_MAX_EMBEDDING_NODES = _env_int("LANG_TO_GRAPH_MAX_EMBEDDING_NODES", 200)

# 토큰 중요도 필터링 비율 (near + far 방식).
# 문장별로 centroid 임베딩과의 cosine 유사도 기준:
#   NEAR_RATIO: centroid에 가장 가까운 토큰 비율 (문장 대표 개념)
#   FAR_RATIO:  centroid에서 가장 먼 토큰 비율 (도메인 특이 개념, 고유명사 등)
# 두 그룹의 합집합을 노드로 생성한다. 최소 TOKEN_IMPORTANCE_MIN개 보장.
TOKEN_IMPORTANCE_NEAR_RATIO = _env_float("TOKEN_IMPORTANCE_NEAR_RATIO", 0.15)
TOKEN_IMPORTANCE_FAR_RATIO  = _env_float("TOKEN_IMPORTANCE_FAR_RATIO",  0.15)
TOKEN_IMPORTANCE_MIN = _env_int("TOKEN_IMPORTANCE_MIN", 1)

# ── LocalGraphExtractor ──────────────────────────────────────────────────────
LOCAL_GRAPH_N_HOP = _env_int("LOCAL_GRAPH_N_HOP", 2)
LOCAL_GRAPH_TRUST_THRESHOLD = _env_float("LOCAL_GRAPH_TRUST_THRESHOLD", 0.2)

# ── InputTypeClassifier ───────────────────────────────────────────────────────
INPUT_CLASSIFIER_EMBED_THRESHOLD = _env_float("INPUT_CLASSIFIER_EMBED_THRESHOLD", 0.70)

# ── ConceptDifferentiation ───────────────────────────────────────────────────
DIFFERENTIATION_THRESHOLD = _env_float("DIFFERENTIATION_THRESHOLD", 0.80)
DIFFERENTIATION_MIN_NEIGHBORS = _env_int("DIFFERENTIATION_MIN_NEIGHBORS", 3)
DIFFERENTIATION_MIN_ALPHA = _env_float("DIFFERENTIATION_MIN_ALPHA", 0.3)
DIFFERENTIATION_ALPHA_DECAY_RATE = _env_float("DIFFERENTIATION_ALPHA_DECAY_RATE", 10.0)

# ── Think 루프 ───────────────────────────────────────────────────────────────
THINK_MAX_LOOPS = _env_int("THINK_MAX_LOOPS", 10)
# 검색 전체(DDG + Wikipedia)에 대한 asyncio 레벨 타임아웃 (초).
# 이 시간 안에 search_fn이 완료되지 않으면 검색 결과 없이 계속 진행한다.
SEARCH_TIMEOUT = _env_float("SEARCH_TIMEOUT", 20.0)

# ── 세계그래프 커밋 강도 ─────────────────────────────────────────────────────
COMMIT_TRUST_STRONG = _env_float("COMMIT_TRUST_STRONG", 0.7)
COMMIT_TRUST_WEAK = _env_float("COMMIT_TRUST_WEAK", 0.15)
COMMIT_STABILITY_STRONG = _env_float("COMMIT_STABILITY_STRONG", 0.6)
COMMIT_STABILITY_WEAK = _env_float("COMMIT_STABILITY_WEAK", 0.1)

# ── GraphToLang ──────────────────────────────────────────────────────────────
# 정렬 후 상위 RATIO 비율의 엣지만 LLM 컨텍스트에 포함한다.
# pairwise 엣지는 노드 수에 대해 O(n²)이므로 비율 기반 절삭이 필요하다.
GRAPH_TO_LANG_EDGE_RATIO = _env_float("GRAPH_TO_LANG_EDGE_RATIO", 0.30)

# ── Ollama LLM ───────────────────────────────────────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

# 생성 모델 선택지에서 제외할 모델 이름 집합.
# 패밀리 메타데이터로 구분할 수 없는 임베딩 전용 모델을 명시적으로 지정한다.
# 환경변수 OLLAMA_EXCLUDED_MODELS에 쉼표로 구분해 추가할 수 있다.
_excluded_from_env: list[str] = [
    m.strip()
    for m in os.getenv("OLLAMA_EXCLUDED_MODELS", "").split(",")
    if m.strip()
]
OLLAMA_EXCLUDED_MODELS: frozenset[str] = frozenset(["embeddinggemma:latest"] + _excluded_from_env)
OLLAMA_TIMEOUT_SECONDS = _env_float("OLLAMA_TIMEOUT_SECONDS", 600.0)
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "gemma3:4b").strip()
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 512)  # GraphToLang 최대 생성 토큰 수
