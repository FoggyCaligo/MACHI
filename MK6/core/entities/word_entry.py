from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class WordEntry:
    """words 테이블의 단일 행.

    단어(surface_form) → 의미 그래프 노드(address_hash) 매핑을 담는다.
    그래프라기보다 해시테이블에 가깝다.
    """

    word_id: str          # UUID
    surface_form: str     # 원형 단어 ("사과", "apple")
    address_hash: str     # → nodes.address_hash
    language: str | None  # 언어 코드 (ko, en, …), nullable
    created_at: datetime
