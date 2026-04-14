from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NodePointer:
    id: int | None = None
    pointer_uid: str = ""
    owner_node_id: int = 0
    referenced_node_id: int = 0
    pointer_type: str = "reference"
    pointer_slot: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    created_from_event_id: int | None = None
    created_at: str | None = None
    is_active: bool = True
