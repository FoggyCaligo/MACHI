from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any
from uuid import uuid4

from core.cognition.direct_node_accessor import DirectNodeAccessor
from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.cognition.meaning_block import MeaningBlock
from core.entities.chat_message import ChatMessage
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from core.entities.node_pointer import NodePointer
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class GraphIngestRequest:
    session_id: str
    turn_index: int
    role: str
    content: str
    attached_files: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    message_uid: str | None = None


@dataclass(slots=True)
class GraphIngestResult:
    message_id: int
    root_event_id: int
    message_uid: str
    block_count: int
    created_node_ids: list[int] = field(default_factory=list)
    reused_node_ids: list[int] = field(default_factory=list)
    created_edge_ids: list[int] = field(default_factory=list)
    supported_edge_ids: list[int] = field(default_factory=list)
    created_pointer_ids: list[int] = field(default_factory=list)
    created_event_ids: list[int] = field(default_factory=list)
    blocks: list[MeaningBlock] = field(default_factory=list)


class GraphIngestService:
    """MK5 hybrid ingest loop.

    Raw messages are persisted first. Sentence boundaries are preserved for
    provenance only. Durable graph nodes are created from reusable meaning blocks.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        hash_resolver: HashResolver | None = None,
        segmenter: InputSegmenter | None = None,
        accessor: DirectNodeAccessor | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.hash_resolver = hash_resolver or HashResolver()
        self.segmenter = segmenter or InputSegmenter(hash_resolver=self.hash_resolver)
        self.accessor = accessor or DirectNodeAccessor(self.hash_resolver)

    def ingest(self, request: GraphIngestRequest) -> GraphIngestResult:
        blocks = self.segmenter.segment(request.content)
        message_uid = request.message_uid or self._new_uid("msg")

        with self.uow_factory() as uow:
            message = uow.chat_messages.add(
                ChatMessage(
                    message_uid=message_uid,
                    session_id=request.session_id,
                    turn_index=request.turn_index,
                    role=request.role,
                    content=request.content,
                    content_hash=self.hash_resolver.content_hash(request.content),
                    attached_files=request.attached_files,
                    metadata=request.metadata,
                )
            )
            parsed_input = {
                "sentence_count": len(self.segmenter.split_sentences(request.content)),
                "blocks": [
                    {
                        "kind": block.block_kind,
                        "text": block.text,
                        "normalized_text": block.normalized_text,
                        "sentence_index": block.sentence_index,
                    }
                    for block in blocks
                ],
            }
            root_event = uow.graph_events.add(
                GraphEvent(
                    event_uid=self._new_uid("evt"),
                    event_type="message_ingested",
                    message_id=message.id,
                    input_text=request.content,
                    parsed_input=parsed_input,
                    effect={"message_uid": message.message_uid},
                )
            )

            result = GraphIngestResult(
                message_id=message.id or 0,
                root_event_id=root_event.id or 0,
                message_uid=message.message_uid,
                block_count=len(blocks),
                blocks=blocks,
            )

            resolved: list[tuple[MeaningBlock, Node]] = []
            sentence_nodes: dict[int, dict[int, Node]] = defaultdict(dict)

            for block in blocks:
                lookup = self.accessor.resolve(uow.nodes, block)
                if lookup.node is None:
                    node = uow.nodes.add(
                        Node(
                            node_uid=self._new_uid("node"),
                            address_hash=lookup.address_hash,
                            node_kind=block.block_kind,
                            raw_value=block.text,
                            normalized_value=block.normalized_text,
                            payload={
                                "source_sentence": block.source_sentence,
                                "source": block.metadata.get("source"),
                                "sentence_index": block.sentence_index,
                                "block_index": block.block_index,
                            },
                            created_from_event_id=root_event.id,
                        )
                    )
                    result.created_node_ids.append(node.id or 0)
                    node_event = uow.graph_events.add(
                        GraphEvent(
                            event_uid=self._new_uid("evt"),
                            event_type="node_created",
                            message_id=message.id,
                            trigger_node_id=node.id,
                            input_text=block.text,
                            parsed_input={"kind": block.block_kind, "normalized_text": block.normalized_text},
                            effect={"address_hash": lookup.address_hash},
                            note="Meaning block persisted as durable node.",
                        )
                    )
                    result.created_event_ids.append(node_event.id or 0)
                else:
                    node = lookup.node
                    result.reused_node_ids.append(node.id or 0)

                resolved.append((block, node))
                sentence_nodes[block.sentence_index][node.id or 0] = node

            self._link_sentence_co_occurrence(
                uow=uow,
                message=message,
                root_event=root_event,
                sentence_nodes=sentence_nodes,
                result=result,
            )
            self._create_partial_reuse_pointers(
                uow=uow,
                message=message,
                root_event=root_event,
                resolved=resolved,
                result=result,
            )
            uow.commit()
            return result

    def _link_sentence_co_occurrence(
        self,
        *,
        uow: UnitOfWork,
        message: ChatMessage,
        root_event: GraphEvent,
        sentence_nodes: dict[int, dict[int, Node]],
        result: GraphIngestResult,
    ) -> None:
        for sentence_index, node_map in sentence_nodes.items():
            if len(node_map) < 2:
                continue
            for source_id, target_id in combinations(sorted(node_map), 2):
                existing = uow.edges.find_active_relation(source_id, target_id, "co_occurs_with")
                if existing is None:
                    edge = uow.edges.add(
                        Edge(
                            edge_uid=self._new_uid("edge"),
                            source_node_id=source_id,
                            target_node_id=target_id,
                            edge_type="co_occurs_with",
                            relation_detail={
                                "scope": "sentence",
                                "sentence_index": sentence_index,
                                "message_id": message.id,
                            },
                            edge_weight=0.25,
                            trust_score=0.6,
                            support_count=1,
                            created_from_event_id=root_event.id,
                        )
                    )
                    result.created_edge_ids.append(edge.id or 0)
                    edge_event = uow.graph_events.add(
                        GraphEvent(
                            event_uid=self._new_uid("evt"),
                            event_type="edge_created",
                            message_id=message.id,
                            trigger_edge_id=edge.id,
                            parsed_input={"sentence_index": sentence_index},
                            effect={"edge_type": "co_occurs_with", "source_node_id": source_id, "target_node_id": target_id},
                            note="Weak same-sentence co-occurrence relation created.",
                        )
                    )
                    result.created_event_ids.append(edge_event.id or 0)
                else:
                    uow.edges.bump_support(existing.id or 0, delta=1, trust_delta=0.02)
                    result.supported_edge_ids.append(existing.id or 0)
                    support_event = uow.graph_events.add(
                        GraphEvent(
                            event_uid=self._new_uid("evt"),
                            event_type="edge_supported",
                            message_id=message.id,
                            trigger_edge_id=existing.id,
                            parsed_input={"sentence_index": sentence_index},
                            effect={"delta": 1, "trust_delta": 0.02},
                            note="Existing co-occurrence relation reinforced.",
                        )
                    )
                    result.created_event_ids.append(support_event.id or 0)

    def _create_partial_reuse_pointers(
        self,
        *,
        uow: UnitOfWork,
        message: ChatMessage,
        root_event: GraphEvent,
        resolved: list[tuple[MeaningBlock, Node]],
        result: GraphIngestResult,
    ) -> None:
        by_sentence: dict[int, list[tuple[MeaningBlock, Node]]] = defaultdict(list)
        for block, node in resolved:
            by_sentence[block.sentence_index].append((block, node))

        for sentence_index, pairs in by_sentence.items():
            for (block_a, node_a), (block_b, node_b) in combinations(pairs, 2):
                if node_a.id == node_b.id:
                    continue
                longer, shorter = self._pick_containment_pair(block_a, node_a, block_b, node_b)
                if longer is None or shorter is None:
                    continue
                existing = uow.node_pointers.find_active(
                    longer[1].id or 0,
                    shorter[1].id or 0,
                    "partial_reuse",
                    pointer_slot="contained_block",
                )
                if existing is not None:
                    continue
                pointer = uow.node_pointers.add(
                    NodePointer(
                        pointer_uid=self._new_uid("ptr"),
                        owner_node_id=longer[1].id or 0,
                        referenced_node_id=shorter[1].id or 0,
                        pointer_type="partial_reuse",
                        pointer_slot="contained_block",
                        detail={
                            "sentence_index": sentence_index,
                            "owner_text": longer[0].normalized_text,
                            "referenced_text": shorter[0].normalized_text,
                        },
                        created_from_event_id=root_event.id,
                    )
                )
                result.created_pointer_ids.append(pointer.id or 0)
                pointer_event = uow.graph_events.add(
                    GraphEvent(
                        event_uid=self._new_uid("evt"),
                        event_type="pointer_created",
                        message_id=message.id,
                        trigger_node_id=longer[1].id,
                        input_text=longer[0].text,
                        parsed_input={"sentence_index": sentence_index},
                        effect={"referenced_node_id": shorter[1].id, "pointer_type": "partial_reuse"},
                        note="Contained meaning block reused through node pointer.",
                    )
                )
                result.created_event_ids.append(pointer_event.id or 0)

    def _pick_containment_pair(
        self,
        block_a: MeaningBlock,
        node_a: Node,
        block_b: MeaningBlock,
        node_b: Node,
    ) -> tuple[tuple[MeaningBlock, Node] | None, tuple[MeaningBlock, Node] | None]:
        text_a = block_a.normalized_text
        text_b = block_b.normalized_text
        if len(text_a) <= len(text_b) and text_a in text_b and text_a != text_b:
            return (block_b, node_b), (block_a, node_a)
        if len(text_b) < len(text_a) and text_b in text_a and text_a != text_b:
            return (block_a, node_a), (block_b, node_b)
        return None, None

    def _new_uid(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex}"
