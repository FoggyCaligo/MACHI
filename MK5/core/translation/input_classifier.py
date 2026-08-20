"""Classify input into natural, code, path, or url."""
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
    stripped = text.strip()
    if _URL_RE.match(stripped):
        return "url"
    if _PATH_RE.search(stripped):
        return "path"
    if _looks_like_code(stripped):
        return "code"
    return None


async def _get_proto_embeddings(embed_fn) -> dict[InputType, list[float]]:
    global _proto_cache
    if _proto_cache is not None:
        return _proto_cache
    async with _proto_lock:
        if _proto_cache is not None:
            return _proto_cache
        embeddings = await asyncio.gather(*[embed_fn(text) for text in _PROTOTYPES.values()])
        _proto_cache = dict(zip(_PROTOTYPES.keys(), embeddings))
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
    embed_fn,
    threshold: float,
) -> InputType:
    result = classify_by_rules(text)
    if result is not None:
        return result

    input_emb, proto_embs = await asyncio.gather(
        embed_fn(text),
        _get_proto_embeddings(embed_fn),
    )

    scores = {
        kind: _cosine(input_emb, emb)
        for kind, emb in proto_embs.items()
    }
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_kind, best_score = sorted_scores[0]
    _, second_score = sorted_scores[1]

    if best_score - second_score < threshold:
        return "natural"
    return best_kind
