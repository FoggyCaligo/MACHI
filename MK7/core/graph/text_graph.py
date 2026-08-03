from __future__ import annotations

import re
from dataclasses import dataclass


_SENTENCE_SPLIT_RE = re.compile(r"(?:\r?\n)+|(?<=[.!?])\s*")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class TokenSpan:
    token: str
    normalized: str
    sentence_index: int
    token_index: int


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]


def extract_tokens(sentence: str) -> list[str]:
    return _TOKEN_RE.findall(sentence)


def normalize_token(token: str) -> str:
    return token.strip().lower()


def tokenize_spans(text: str) -> list[TokenSpan]:
    spans: list[TokenSpan] = []
    for sentence_index, sentence in enumerate(split_sentences(text)):
        for token_index, token in enumerate(extract_tokens(sentence)):
            normalized = normalize_token(token)
            if not normalized:
                continue
            spans.append(
                TokenSpan(
                    token=token,
                    normalized=normalized,
                    sentence_index=sentence_index,
                    token_index=token_index,
                )
            )
    return spans
