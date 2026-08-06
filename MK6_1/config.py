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


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


DB_PATH = os.getenv("MK6_DB_PATH", "data/memory.db")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "nomic-embed-text").strip()
EMBEDDING_TIMEOUT_SECONDS = _env_float("EMBEDDING_TIMEOUT_SECONDS", 10.0)
LANG_TO_GRAPH_SIMILARITY_THRESHOLD = _env_float("LANG_TO_GRAPH_SIMILARITY_THRESHOLD", 0.75)
LANG_TO_GRAPH_MAX_EMBEDDING_NODES = _env_int("LANG_TO_GRAPH_MAX_EMBEDDING_NODES", 200)
TOKEN_IMPORTANCE_NEAR_RATIO = _env_float("TOKEN_IMPORTANCE_NEAR_RATIO", 0.20)
TOKEN_IMPORTANCE_FAR_RATIO = _env_float("TOKEN_IMPORTANCE_FAR_RATIO", 0.20)
TOKEN_IMPORTANCE_MIN = _env_int("TOKEN_IMPORTANCE_MIN", 1)
LOCAL_GRAPH_N_HOP = _env_int("LOCAL_GRAPH_N_HOP", 2)
LOCAL_GRAPH_TRUST_THRESHOLD = _env_float("LOCAL_GRAPH_TRUST_THRESHOLD", 0.2)
INPUT_CLASSIFIER_EMBED_THRESHOLD = _env_float("INPUT_CLASSIFIER_EMBED_THRESHOLD", 0.70)
DIFFERENTIATION_THRESHOLD = _env_float("DIFFERENTIATION_THRESHOLD", 0.80)
DIFFERENTIATION_MIN_NEIGHBORS = _env_int("DIFFERENTIATION_MIN_NEIGHBORS", 3)
DIFFERENTIATION_MIN_ALPHA = _env_float("DIFFERENTIATION_MIN_ALPHA", 0.3)
DIFFERENTIATION_ALPHA_DECAY_RATE = _env_float("DIFFERENTIATION_ALPHA_DECAY_RATE", 10.0)
THINK_MAX_LOOPS = _env_int("THINK_MAX_LOOPS", 10)
THINK_ACTIVATION_HOPS = _env_int("THINK_ACTIVATION_HOPS", 2)
THINK_CONCLUSION_GRAPH_LIMIT = _env_int("THINK_CONCLUSION_GRAPH_LIMIT", 5)
THINK_GOAL_SCORE_MIN_DELTA = _env_float("THINK_GOAL_SCORE_MIN_DELTA", 0.01)
SEARCH_TIMEOUT = _env_float("SEARCH_TIMEOUT", 20.0)
COMMIT_TRUST_STRONG = _env_float("COMMIT_TRUST_STRONG", 0.7)
COMMIT_TRUST_WEAK = _env_float("COMMIT_TRUST_WEAK", 0.15)
COMMIT_STABILITY_STRONG = _env_float("COMMIT_STABILITY_STRONG", 0.6)
COMMIT_STABILITY_WEAK = _env_float("COMMIT_STABILITY_WEAK", 0.1)
WORLD_EDGE_REINFORCE_ALPHA = _env_float("WORLD_EDGE_REINFORCE_ALPHA", 0.5)
GRAPH_TO_LANG_EDGE_RATIO = _env_float("GRAPH_TO_LANG_EDGE_RATIO", 0.30)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
_excluded_from_env: list[str] = [m.strip() for m in os.getenv("OLLAMA_EXCLUDED_MODELS", "").split(",") if m.strip()]
OLLAMA_EXCLUDED_MODELS: frozenset[str] = frozenset(["embeddinggemma:latest"] + _excluded_from_env)
OLLAMA_TIMEOUT_SECONDS = _env_float("OLLAMA_TIMEOUT_SECONDS", 600.0)
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "gemma3:4b").strip()
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 2048)
OLLAMA_THINK = _env_bool("OLLAMA_THINK", False)
