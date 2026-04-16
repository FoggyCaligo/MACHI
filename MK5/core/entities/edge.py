from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Edge:
    id: int | None = None
    edge_uid: str = ""
    source_node_id: int = 0
    target_node_id: int = 0
    edge_family: str = "relation"
    connect_type: str = "flow"
    relation_detail: dict[str, Any] = field(default_factory=dict)
    edge_weight: float = 0.1
    trust_score: float = 0.5
    support_count: int = 0
    conflict_count: int = 0
    contradiction_pressure: float = 0.0
    revision_candidate_flag: bool = False
    created_from_event_id: int | None = None
    last_supported_at: str | None = None
    last_conflicted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    is_active: bool = True

    @property
    def connect_semantics(self) -> str:
        value = self.relation_detail.get("connect_semantics")
        return ' '.join(str(value or '').split()).strip()

    @property
    def display_label(self) -> str:
        semantics = self.connect_semantics
        if semantics:
            return f"{self.edge_family}/{self.connect_type}/{semantics}"
        return f"{self.edge_family}/{self.connect_type}"
