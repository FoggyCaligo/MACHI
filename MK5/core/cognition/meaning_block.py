from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MeaningBlock:
    """A reusable semantic chunk extracted from one message.

    The block is smaller than a full sentence, but larger and more reusable than
    a raw token. It is the durable candidate unit for early MK5 graph ingest.
    """

    text: str
    normalized_text: str
    block_kind: str
    sentence_index: int
    block_index: int
    source_sentence: str
    metadata: dict[str, Any] = field(default_factory=dict)
