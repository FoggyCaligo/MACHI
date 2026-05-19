"""InputTypeClassifier — 입력 문자열의 형식 타입을 분류한다.

이 모듈은 자연어 의미/의도 판단기가 아니다. URL, 파일 경로, 코드처럼
LangToGraph 토큰화에 그대로 넣으면 안 되는 비자연어 입력을 분리하는
형식 게이트와, 모호한 경우의 임베딩 기반 형식 분류만 담당한다.
"""
from __future__ import annotations

import asyncio
import math
import re
from typing import Literal

InputType = Literal["natural", "code", "path", "url"]


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

_CODE_KEYWORDS_RE = re.compile(
    r"\b(?:def |class |function |const |let |var |import |from |return |"
    r"if\s*\(|for\s*\(|while\s*\()\b"
    r"|[{};\(\)]"
)
_INDENT_BLOCK_RE = re.compile(r"(?:^|\n)([ \t]{2,})\S", re.MULTILINE)

_PROTOTYPES: dict[InputType, str] = {
    "natural": "This is a natural language sentence about everyday topics.",
    "code": "def add(a, b): return a + b  # Python function",
    "path": "/usr/local/bin/python3.10",
    "url": "https://www.example.com/path/to/page",
}

_proto_cache: dict[InputType, list[float]] | None = None
_proto_lock = asyncio.Lock()


def _looks_like_code(text: str) -> bool:
    has_indent = bool(_INDENT_BLOCK_RE.search(text))
    keyword_count = len(_CODE_KEYWORDS_RE.findall(text))
    return has_indent and keyword_count >= 2


def classify_by_rules(text: str) -> InputType | None:
    """형식상 명확한 URL/path/code만 분류한다.

    자연어 의미, 발화 의도, 주제, 관계, 정체성 판단에는 이 규칙을 사용하지 않는다.
    """
    stripped = text.strip()
    if _URL_RE.match(stripped):
        return "url"
    if _PATH_RE.search(stripped):
        return "path"
    if _looks_like_code(stripped):
        return "code"
    return None


async def _get_proto_embeddings(embed_fn) -> dict[InputType, list[float]]:
    """프로토타입 임베딩을 반환한다. 임베딩 실패는 호출자에게 드러낸다."""
    global _proto_cache
    if _proto_cache is not None:
        return _proto_cache
    async with _proto_lock:
        if _proto_cache is not None:
            return _proto_cache
        embs = await asyncio.gather(*[embed_fn(text) for text in _PROTOTYPES.values()])
        _proto_cache = dict(zip(_PROTOTYPES.keys(), embs))
    return _proto_cache


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        raise ValueError("Cannot classify input with a zero-length embedding vector")
    return dot / (na * nb)


async def classify(
    text: str,
    embed_fn,
    threshold: float,
) -> InputType:
    """입력 형식 타입을 분류한다.

    규칙으로 명확한 비자연어 형식이면 즉시 반환한다. 그 외에는 입력 임베딩과
    형식 프로토타입 임베딩을 비교한다. 임베딩 실패는 natural로 숨기지 않는다.
    """
    result = classify_by_rules(text)
    if result is not None:
        return result

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
