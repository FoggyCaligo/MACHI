from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from core.cognition.hash_resolver import HashResolver
from core.cognition.meaning_block import MeaningBlock

_SENTENCE_SPLIT_RE = re.compile(r"(?:\r?\n)+|(?<=[.!?])\s+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_+\-./#]+|[가-힣]{2,}")
_RELATION_SYMBOLS = ("->", "→", "=", "/")


@dataclass(slots=True)
class InputSegmenter:
    """Early MK5 ingest segmenter without lexical keyword heuristics.

    Design note:
    - No sentence kind is inferred from semantic cue words.
    - Sentence-level blocks are classified only from surface structure
      (question mark / relation symbols) plus token extraction.
    - Durable reusable units are still smaller than full sentences.
    """

    hash_resolver: HashResolver
    max_token_blocks_per_sentence: int = 12

    _KOREAN_PARTICLES: ClassVar[tuple[str, ...]] = (
        "으로", "에서", "에게", "까지", "부터", "처럼", "보다", "하고",
        "은", "는", "이", "가", "을", "를", "에", "의", "도", "로", "과", "와", "만", "랑",
    )
    _STOPWORDS: ClassVar[set[str]] = {
        "그럼", "그러면", "그리고", "하지만", "또", "지금", "이번", "그것", "이것", "저것",
        "하는", "되는", "있다", "없다", "한다", "했다", "하기", "처럼", "정도", "기준",
    }

    def split_sentences(self, content: str) -> list[str]:
        sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(content) if part and part.strip()]
        return sentences or ([content.strip()] if content.strip() else [])

    def segment(self, content: str) -> list[MeaningBlock]:
        sentences = self.split_sentences(content)
        blocks: list[MeaningBlock] = []
        seen: set[tuple[int, str, str]] = set()

        for sentence_index, sentence in enumerate(sentences):
            block_index = 0
            normalized_sentence = self.hash_resolver.normalize_text(sentence)
            if not normalized_sentence:
                continue

            sentence_kind = self._sentence_level_kind(sentence)
            key = (sentence_index, sentence_kind, normalized_sentence)
            if key not in seen:
                blocks.append(
                    MeaningBlock(
                        text=sentence,
                        normalized_text=normalized_sentence,
                        block_kind=sentence_kind,
                        sentence_index=sentence_index,
                        block_index=block_index,
                        source_sentence=sentence,
                        metadata={"source": "sentence_structure"},
                    )
                )
                seen.add(key)
                block_index += 1

            token_count = 0
            for token in self._extract_token_candidates(sentence):
                if token_count >= self.max_token_blocks_per_sentence:
                    break
                normalized_token = self._normalize_token(token)
                if not normalized_token or normalized_token in self._STOPWORDS:
                    continue
                key = (sentence_index, "noun_phrase", normalized_token)
                if key in seen:
                    continue
                blocks.append(
                    MeaningBlock(
                        text=token,
                        normalized_text=normalized_token,
                        block_kind="noun_phrase",
                        sentence_index=sentence_index,
                        block_index=block_index,
                        source_sentence=sentence,
                        metadata={"source": "token_rule"},
                    )
                )
                seen.add(key)
                token_count += 1
                block_index += 1

        if not blocks and content.strip():
            normalized = self.hash_resolver.normalize_text(content)
            blocks.append(
                MeaningBlock(
                    text=content.strip(),
                    normalized_text=normalized,
                    block_kind="statement_phrase",
                    sentence_index=0,
                    block_index=0,
                    source_sentence=content.strip(),
                    metadata={"source": "fallback"},
                )
            )
        return blocks

    def _sentence_level_kind(self, sentence: str) -> str:
        stripped = sentence.strip()
        if stripped.endswith('?') or stripped.endswith('？'):
            return 'inquiry_phrase'
        if any(symbol in stripped for symbol in _RELATION_SYMBOLS):
            return 'relation_phrase'
        return 'statement_phrase'

    def _extract_token_candidates(self, sentence: str) -> list[str]:
        return _TOKEN_RE.findall(sentence)

    def _normalize_token(self, token: str) -> str:
        token = token.strip().lower()
        for particle in self._KOREAN_PARTICLES:
            if len(token) > len(particle) + 1 and token.endswith(particle):
                token = token[: -len(particle)]
                break
        token = token.strip(" ,./!?;:'\"()[]{}")
        return self.hash_resolver.normalize_text(token)
