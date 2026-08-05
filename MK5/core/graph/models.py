from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class GraphNode:
    node_id: str
    labels: list[str]
    node_type: str = "concept"
    payload: dict = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source_id: str
    target_id: str
    relation: str
    payload: dict = field(default_factory=dict)


@dataclass(slots=True)
class UserTurnRecord:
    user_id: str
    text: str
    session_id: str | None = None
