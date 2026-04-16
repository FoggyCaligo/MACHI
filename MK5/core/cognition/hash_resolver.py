from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from core.cognition.meaning_block import MeaningBlock

_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"[\s\.,!?;:~]+$")


@dataclass(slots=True)
class HashResolver:
    """Build stable, direct-address hashes for messages and meaning blocks."""

    digest_size: int = 16

    def normalize_text(self, text: str) -> str:
        normalized = text.strip().lower()
        normalized = _WHITESPACE_RE.sub(" ", normalized)
        normalized = _TRAILING_PUNCT_RE.sub("", normalized)
        return normalized

    def content_hash(self, text: str) -> str:
        normalized = self.normalize_text(text)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[: self.digest_size * 2]

    def address_for(self, block: MeaningBlock) -> str:
        payload = block.normalized_text
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[: self.digest_size * 2]
