from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.cognition.meaning_block import MeaningBlock
from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.node_pointer import NodePointer


@dataclass(slots=True)
class ActivatedNode:
    node: Node
    activation_score: float
    activated_by: str
    matched_blocks: list[MeaningBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThoughtView:
    session_id: str
    message_text: str
    seed_blocks: list[MeaningBlock] = field(default_factory=list)
    seed_nodes: list[ActivatedNode] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    pointers: list[NodePointer] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
