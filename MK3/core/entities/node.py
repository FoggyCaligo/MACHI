from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Node:
    id: int | None = None
    node_uid: str = ""
    address_hash: str = ""
    node_kind: str = "node"
    raw_value: str = ""
    normalized_value: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    trust_score: float = 0.5
    stability_score: float = 0.5
    revision_state: str = "stable"
    created_from_event_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    is_active: bool = True

    @property
    def data(self) -> dict[str, Any]:
        return self.payload

    @property
    def note(self) -> str:
        return ' '.join(str(self.payload.get('note') or '').split()).strip()
