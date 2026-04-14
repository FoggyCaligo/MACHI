from __future__ import annotations

from collections.abc import Sequence

from core.cognition.meaning_block import MeaningBlock
from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.node_pointer import NodePointer
from core.entities.thought_view import ActivatedNode, ThoughtView


class ThoughtViewBuilder:
    def build(
        self,
        *,
        session_id: str,
        message_text: str,
        seed_blocks: Sequence[MeaningBlock],
        seed_nodes: Sequence[ActivatedNode],
        nodes: Sequence[Node],
        edges: Sequence[Edge],
        pointers: Sequence[NodePointer],
        metadata: dict | None = None,
    ) -> ThoughtView:
        return ThoughtView(
            session_id=session_id,
            message_text=message_text,
            seed_blocks=list(seed_blocks),
            seed_nodes=list(seed_nodes),
            nodes=list(nodes),
            edges=list(edges),
            pointers=list(pointers),
            metadata=metadata or {},
        )
