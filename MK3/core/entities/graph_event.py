from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GraphEvent:
    id: int | None = None
    event_uid: str = ""
    event_type: str = ""
    message_id: int | None = None
    trigger_node_id: int | None = None
    trigger_edge_id: int | None = None
    input_text: str | None = None
    parsed_input: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)
    note: str | None = None
    created_at: str | None = None
