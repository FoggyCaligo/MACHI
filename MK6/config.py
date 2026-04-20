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

# 토큰 중요도 필터링 비율.
# 문장별로 centroid 임베딩 기반 cosine 유사도 상위 RATIO 비율 토큰만 노드로 생성한다.
# 임베딩 없는 토큰은 레이블 길이 기반 폴백. 최소 TOKEN_IMPORTANCE_MIN개 보장.
TOKEN_IMPORTANCE_RATIO = _env_float("TOKEN_IMPORTANCE_RATIO", 0.20)
TOKEN_IMPORTANCE_MIN = _env_int("TOKEN_IMPORTANCE_MIN", 2)

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

# ── 세계그래프 커밋 강도 ─────────────────────────────────────────────────────
COMMIT_TRUST_STRONG = _env_float("COMMIT_TRUST_STRONG", 0.7)
COMMIT_TRUST_WEAK = _env_float("COMMIT_TRUST_WEAK", 0.15)
COMMIT_STABILITY_STRONG = _env_float("COMMIT_STABILITY_STRONG", 0.6)
COMMIT_STABILITY_WEAK = _env_float("COMMIT_STABILITY_WEAK", 0.1)

# ── Ollama LLM ───────────────────────────────────────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_TIMEOUT_SECONDS = _env_float("OLLAMA_TIMEOUT_SECONDS", 600.0)
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "").strip()
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 512)  # GraphToLang 최대 생성 토큰 수
