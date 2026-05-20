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
TOKEN_IMPORTANCE_NEAR_RATIO = _env_float("TOKEN_IMPORTANCE_NEAR_RATIO", 0.20)
TOKEN_IMPORTANCE_FAR_RATIO  = _env_float("TOKEN_IMPORTANCE_FAR_RATIO",  0.20)
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
# Think activation은 기본 2-hop으로 시작한다. TurnGoalView가 명시 구조로 승격되면
# 이 값과 depth decay 정책을 다시 조정할 수 있다.
THINK_ACTIVATION_HOPS = _env_int("THINK_ACTIVATION_HOPS", 2)
THINK_CONCLUSION_GRAPH_LIMIT = _env_int("THINK_CONCLUSION_GRAPH_LIMIT", 5)
# patch overlap이 높아도 goal alignment가 이 값 이상 개선되면 계속 사고한다.
THINK_GOAL_SCORE_MIN_DELTA = _env_float("THINK_GOAL_SCORE_MIN_DELTA", 0.01)
# 검색 전체(DDG + Wikipedia)에 대한 asyncio 레벨 타임아웃 (초).
# 이 시간 안에 search_fn이 완료되지 않으면 검색 결과 없이 계속 진행한다.
SEARCH_TIMEOUT = _env_float("SEARCH_TIMEOUT", 20.0)
# relation extractor LLM 호출 전용 timeout (초).
# 로컬 Ollama 모델은 JSON 추출 프롬프트에서 120초를 넘는 경우가 있어 넉넉히 둔다.
SEARCH_RELATION_EXTRACTOR_TIMEOUT = _env_float("SEARCH_RELATION_EXTRACTOR_TIMEOUT", 300.0)
SEARCH_RELATION_EXTRACTOR_MAX_ITEMS = _env_int("SEARCH_RELATION_EXTRACTOR_MAX_ITEMS", 4)
SEARCH_RELATION_EXTRACTOR_MAX_SNIPPET_CHARS = _env_int("SEARCH_RELATION_EXTRACTOR_MAX_SNIPPET_CHARS", 180)
SEARCH_RELATION_EXTRACTOR_NUM_PREDICT = _env_int("SEARCH_RELATION_EXTRACTOR_NUM_PREDICT", 1024)
# none: 일반 생성 + parser/validator, json: provider JSON mode, schema: provider JSON schema.
# 일부 로컬 Ollama 모델은 JSON mode에서 지연/빈 wrapper를 만들 수 있으므로 기본값은 none이다.
SEARCH_RELATION_EXTRACTOR_RESPONSE_FORMAT = os.getenv(
    "SEARCH_RELATION_EXTRACTOR_RESPONSE_FORMAT",
    "none",
).strip().lower()

# ── 세계그래프 커밋 강도 ─────────────────────────────────────────────────────
COMMIT_TRUST_STRONG = _env_float("COMMIT_TRUST_STRONG", 0.7)
COMMIT_TRUST_WEAK = _env_float("COMMIT_TRUST_WEAK", 0.15)
COMMIT_STABILITY_STRONG = _env_float("COMMIT_STABILITY_STRONG", 0.6)
COMMIT_STABILITY_WEAK = _env_float("COMMIT_STABILITY_WEAK", 0.1)
# 같은 endpoint의 관측 edge가 반복될 때 세계 그래프에 반영할 강화 비율.
# 1.0이면 기존처럼 현재 관측치를 전량 누적하고, 0.5이면 현재 관측치의 절반만 누적한다.
WORLD_EDGE_REINFORCE_ALPHA = _env_float("WORLD_EDGE_REINFORCE_ALPHA", 0.5)

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
OLLAMA_TIMEOUT_SECONDS = _env_float("OLLAMA_TIMEOUT_SECONDS", 900.0)
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "gemma3:4b").strip()
# thinking 계열 모델은 응답 전 내부 사고 토큰으로 예산을 소진할 수 있으므로
# GraphToLang 기본 생성 예산을 512보다 넉넉하게 둔다.
OLLAMA_NUM_PREDICT = _env_int("OLLAMA_NUM_PREDICT", 2048)
# Ollama chat API가 지원하는 경우 thinking 출력을 비활성화한다.
# 지원하지 않는 모델/버전에서는 서버가 무시할 수 있으므로, 최종 응답 계약은
# ollama_client.chat()의 content 검증이 담당한다.
OLLAMA_THINK = _env_bool("OLLAMA_THINK", False)
