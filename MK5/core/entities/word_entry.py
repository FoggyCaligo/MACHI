from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class WordEntry:
    """words 테이블의 단일 표면형-노드 링크.

    words는 단어(surface_form)를 단일 의미 노드에 고정하는 테이블이 아니라,
    표면형과 의미 그래프 노드(address_hash) 사이의 후보 링크 집합이다.

    같은 surface_form은 여러 address_hash에 연결될 수 있고,
    같은 address_hash도 여러 surface_form을 가질 수 있다.
    중복은 (surface_form, address_hash) 쌍 기준으로만 금지된다.
    """

    word_id: str          # UUID
    surface_form: str     # 정규화된 표면형 ("사과", "apple")
    address_hash: str     # → nodes.address_hash
    language: str | None  # 언어 코드 (ko, en, …), nullable
    created_at: datetime
