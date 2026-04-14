from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from core.activation.pattern_detector import PatternDetector
from core.activation.thought_view_builder import ThoughtViewBuilder
from core.cognition.direct_node_accessor import DirectNodeAccessor
from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.cognition.meaning_block import MeaningBlock
from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.node_pointer import NodePointer
from core.entities.subgraph_pattern import PatternMatch
from core.entities.thought_view import ActivatedNode, ThoughtView
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class ActivationRequest:
    session_id: str
    content: str
    max_seed_nodes: int = 12
    max_neighbor_edges: int = 64
    max_neighbors: int = 48
    include_pointer_expansion: bool = True


class ActivationEngine:
    """Create a local thought view from the durable graph.

    The engine resolves reusable meaning blocks to durable seed nodes, expands
    one hop through active edges, optionally follows active pointers, and returns
    a bounded subgraph for later thinking.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        hash_resolver: HashResolver | None = None,
        segmenter: InputSegmenter | None = None,
        accessor: DirectNodeAccessor | None = None,
        thought_view_builder: ThoughtViewBuilder | None = None,
        pattern_detector: PatternDetector | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.hash_resolver = hash_resolver or HashResolver()
        self.segmenter = segmenter or InputSegmenter(hash_resolver=self.hash_resolver)
        self.accessor = accessor or DirectNodeAccessor(self.hash_resolver)
        self.thought_view_builder = thought_view_builder or ThoughtViewBuilder()
        self.pattern_detector = pattern_detector or PatternDetector()

    def build_view(self, request: ActivationRequest) -> ThoughtView:
        seed_blocks = self.segmenter.segment(request.content)
        with self.uow_factory() as uow:
            seed_nodes = self._resolve_seed_nodes(uow, seed_blocks, request.max_seed_nodes)
            seed_node_ids = [seed.node.id for seed in seed_nodes if seed.node.id is not None]

            local_edges = self._collect_neighbor_edges(uow, seed_node_ids, request.max_neighbor_edges)
            neighbor_nodes = self._collect_neighbor_nodes(uow, seed_nodes, local_edges, request.max_neighbors)
            all_nodes = self._merge_nodes(seed_nodes, neighbor_nodes)
            pointers = self._collect_pointers(uow, all_nodes, request.include_pointer_expansion)

            metadata = {
                'seed_block_count': len(seed_blocks),
                'seed_node_count': len(seed_nodes),
                'neighbor_edge_count': len(local_edges),
                'pointer_count': len(pointers),
            }
            thought_view = self.thought_view_builder.build(
                session_id=request.session_id,
                message_text=request.content,
                seed_blocks=seed_blocks,
                seed_nodes=seed_nodes,
                nodes=all_nodes,
                edges=local_edges,
                pointers=pointers,
                metadata=metadata,
            )

            # Detect and activate patterns in the thought view
            activated_patterns = self.pattern_detector.detect_patterns(thought_view)
            thought_view.activated_patterns = activated_patterns

            return thought_view

    def _resolve_seed_nodes(
        self,
        uow: UnitOfWork,
        seed_blocks: list[MeaningBlock],
        max_seed_nodes: int,
    ) -> list[ActivatedNode]:
        grouped: dict[int, ActivatedNode] = {}
        unresolved_bonus = 0.0
        for block in seed_blocks:
            lookup = self.accessor.resolve(uow.nodes, block)
            if lookup.node is None or lookup.node.id is None:
                unresolved_bonus += 0.01
                continue
            score = self._seed_score(lookup.node, block, reused_via=lookup.reused_via)
            current = grouped.get(lookup.node.id)
            if current is None:
                grouped[lookup.node.id] = ActivatedNode(
                    node=lookup.node,
                    activation_score=score,
                    activated_by=lookup.reused_via or 'seed',
                    matched_blocks=[block],
                    metadata={'reused_via': lookup.reused_via, 'unresolved_bonus': unresolved_bonus},
                )
            else:
                current.activation_score = max(current.activation_score, score)
                current.matched_blocks.append(block)
        ordered = sorted(
            grouped.values(),
            key=lambda item: (
                item.activation_score,
                item.node.trust_score,
                item.node.stability_score,
                -(item.node.id or 0),
            ),
            reverse=True,
        )
        return ordered[:max_seed_nodes]

    def _collect_neighbor_edges(
        self,
        uow: UnitOfWork,
        seed_node_ids: list[int],
        max_neighbor_edges: int,
    ) -> list[Edge]:
        if not seed_node_ids:
            return []
        edges = list(uow.edges.list_edges_for_nodes(seed_node_ids, active_only=True))
        edges.sort(
            key=lambda edge: (
                edge.trust_score,
                edge.edge_weight,
                edge.support_count,
                -edge.conflict_count,
                -edge.contradiction_pressure,
            ),
            reverse=True,
        )
        return edges[:max_neighbor_edges]

    def _collect_neighbor_nodes(
        self,
        uow: UnitOfWork,
        seed_nodes: list[ActivatedNode],
        edges: list[Edge],
        max_neighbors: int,
    ) -> list[Node]:
        seed_ids = {seed.node.id for seed in seed_nodes if seed.node.id is not None}
        neighbor_ids: list[int] = []
        for edge in edges:
            for node_id in (edge.source_node_id, edge.target_node_id):
                if node_id not in seed_ids and node_id not in neighbor_ids:
                    neighbor_ids.append(node_id)
                    if len(neighbor_ids) >= max_neighbors:
                        break
            if len(neighbor_ids) >= max_neighbors:
                break
        return list(uow.nodes.list_by_ids(neighbor_ids)) if neighbor_ids else []

    def _merge_nodes(self, seed_nodes: list[ActivatedNode], neighbor_nodes: list[Node]) -> list[Node]:
        by_id: dict[int, Node] = {}
        for activated in seed_nodes:
            if activated.node.id is not None:
                by_id[activated.node.id] = activated.node
        for node in neighbor_nodes:
            if node.id is not None:
                by_id.setdefault(node.id, node)
        return list(by_id.values())

    def _collect_pointers(
        self,
        uow: UnitOfWork,
        nodes: list[Node],
        include_pointer_expansion: bool,
    ) -> list[NodePointer]:
        if not include_pointer_expansion:
            return []
        collected: list[NodePointer] = []
        seen_ids: set[int] = set()
        for node in nodes:
            if node.id is None:
                continue
            for pointer in uow.node_pointers.list_by_owner(node.id, active_only=True):
                if pointer.id is not None and pointer.id not in seen_ids:
                    collected.append(pointer)
                    seen_ids.add(pointer.id)
        return collected

    def _seed_score(self, node: Node, block: MeaningBlock, *, reused_via: str | None) -> float:
        base = node.trust_score * 0.45 + node.stability_score * 0.35
        via_bonus = 0.15 if reused_via == 'address_hash' else 0.08
        kind_bonus = 0.05 if node.node_kind == block.block_kind else 0.0
        exact_bonus = 0.05 if (node.normalized_value or '') == block.normalized_text else 0.0
        return round(base + via_bonus + kind_bonus + exact_bonus, 6)
