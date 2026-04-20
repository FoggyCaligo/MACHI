"""InputTypeClassifier — 입력 문자열의 타입을 분류한다.

방식: 규칙 우선 → 임베딩 폴백 (D안)
"""
from __future__ import annotations

import re
from typing import Literal

InputType = Literal["natural", "code", "path", "url"]

# ── 1단계: 규칙 기반 ──────────────────────────────────────────────────────────

_URL_RE = re.compile(r"^(?:https?|ftp)://", re.IGNORECASE)

_PATH_EXTENSIONS = (
    r"\.(?:py|js|ts|jsx|tsx|md|txt|json|yaml|yml|toml|ini|cfg|sh|bash|"
    r"java|c|cpp|h|hpp|go|rs|rb|php|html|css|sql|xml|csv|log|lock|"
    r"dockerfile|makefile)"
)
_PATH_RE = re.compile(
    r"(?:^[./\\]|[/\\])" + _PATH_EXTENSIONS + r"(?:\b|$)",
    re.IGNORECASE,
)

# 코드 판단: 들여쓰기 블록 + 코드 키워드
_CODE_KEYWORDS_RE = re.compile(
    r"\b(?:def |class |function |const |let |var |import |from |return |"
    r"if\s*\(|for\s*\(|while\s*\()\b"
    r"|[{};\(\)]"
)
_INDENT_BLOCK_RE = re.compile(r"(?:^|\n)([ \t]{2,})\S", re.MULTILINE)


def _looks_like_code(text: str) -> bool:
    has_indent = bool(_INDENT_BLOCK_RE.search(text))
    keyword_count = len(_CODE_KEYWORDS_RE.findall(text))
    return has_indent and keyword_count >= 2


def classify_by_rules(text: str) -> InputType | None:
    """규칙으로 명확하게 분류할 수 있으면 타입을 반환한다.

    모호하면 None을 반환해 임베딩 폴백을 유도한다.
    """
    stripped = text.strip()
    if _URL_RE.match(stripped):
        return "url"
    if _PATH_RE.search(stripped):
        return "path"
    if _looks_like_code(stripped):
        return "code"
    return None


# ── 2단계: 임베딩 폴백 ───────────────────────────────────────────────────────

import asyncio
import math

# 프로토타입 문장 (임베딩 기준점)
_PROTOTYPES: dict[InputType, str] = {
    "natural": "This is a natural language sentence about everyday topics.",
    "code":    "def add(a, b): return a + b  # Python function",
    "path":    "/usr/local/bin/python3.10",
    "url":     "https://www.example.com/path/to/page",
}

# 프로토타입 임베딩 캐시 — 서버 수명 동안 최초 1회만 계산
_proto_cache: dict[InputType, list[float]] | None = None
_proto_lock = asyncio.Lock()


async def _get_proto_embeddings(embed_fn) -> dict[InputType, list[float]]:
    """프로토타입 임베딩을 반환한다. 최초 호출 시 한 번만 계산하고 캐싱한다."""
    global _proto_cache
    if _proto_cache is not None:
        return _proto_cache
    async with _proto_lock:
        if _proto_cache is not None:   # double-checked locking
            return _proto_cache
        embs = await asyncio.gather(
            *[embed_fn(text) for text in _PROTOTYPES.values()]
        )
        _proto_cache = dict(zip(_PROTOTYPES.keys(), embs))
    return _proto_cache


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def classify(
    text: str,
    embed_fn,  # async (str) -> list[float]
    threshold: float,
) -> InputType:
    """입력 타입을 분류한다.

    Args:
        text:       분류할 입력 문자열
        embed_fn:   async 임베딩 함수 (str → list[float])
        threshold:  임베딩 유사도 차이 threshold.
                    최고 유사도와 2위 유사도의 차이가 이 값 미만이면
                    "natural"로 안전 폴백한다.
    """
    result = classify_by_rules(text)
    if result is not None:
        return result

    # 입력 임베딩과 캐시된 프로토타입 임베딩을 병렬 획득
    input_emb, proto_embs = await asyncio.gather(
        embed_fn(text),
        _get_proto_embeddings(embed_fn),
    )

    scores: dict[InputType, float] = {
        kind: _cosine(input_emb, emb)
        for kind, emb in proto_embs.items()
    }

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_kind, best_score = sorted_scores[0]
    _, second_score = sorted_scores[1]

    if best_score - second_score < threshold:
        return "natural"

    return best_kind
