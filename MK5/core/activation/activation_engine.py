from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
import hashlib

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
            previous_topic_terms = self._latest_topic_terms(uow, request.session_id)
            previous_tone_hint = self._latest_tone_hint(uow, request.session_id)
            current_topic_terms = self._extract_topic_terms(seed_blocks, seed_nodes)
            topic_overlap_count = len(set(previous_topic_terms).intersection(current_topic_terms))
            recent_memory_messages = self._recent_conversation_memory(uow, request.session_id)
            identity_nodes = self._session_identity_nodes(uow, request.session_id)

            local_edges = self._collect_neighbor_edges(uow, seed_node_ids, request.max_neighbor_edges)
            concept_hop_edges = self._expand_concept_hops(
                uow,
                seed_node_ids=seed_node_ids,
                existing_edges=local_edges,
            )
            all_edges = local_edges + concept_hop_edges
            neighbor_nodes = self._collect_neighbor_nodes(uow, seed_nodes, all_edges, request.max_neighbors)
            all_nodes = self._merge_nodes(seed_nodes, neighbor_nodes + identity_nodes)
            pointers = self._collect_pointers(uow, all_nodes, request.include_pointer_expansion)

            metadata = {
                'seed_block_count': len(seed_blocks),
                'seed_node_count': len(seed_nodes),
                'neighbor_edge_count': len(local_edges),
                'concept_hop_edge_count': len(concept_hop_edges),
                'pointer_count': len(pointers),
                'current_topic_terms': current_topic_terms,
                'previous_topic_terms': previous_topic_terms,
                'previous_tone_hint': previous_tone_hint,
                'topic_overlap_count': topic_overlap_count,
                'recent_memory_messages': recent_memory_messages,
                'recent_memory_count': len(recent_memory_messages),
                'identity_node_ids': [node.id for node in identity_nodes if node.id is not None],
                'identity_terms': self._extract_identity_terms(identity_nodes),
            }
            thought_view = self.thought_view_builder.build(
                session_id=request.session_id,
                message_text=request.content,
                seed_blocks=seed_blocks,
                seed_nodes=seed_nodes,
                nodes=all_nodes,
                edges=all_edges,
                pointers=pointers,
                metadata=metadata,
            )

            # Detect and activate patterns in the thought view
            activated_patterns = self.pattern_detector.detect_patterns(thought_view)
            thought_view.activated_patterns = activated_patterns

            return thought_view

    def _latest_topic_terms(self, uow: UnitOfWork, session_id: str) -> list[str]:
        recent_messages = list(uow.chat_messages.list_by_session(session_id, limit=24))
        for message in reversed(recent_messages):
            if getattr(message, 'role', None) != 'assistant':
                continue
            metadata = getattr(message, 'metadata', {}) or {}
            snapshot = metadata.get('intent_snapshot') or {}
            topic_terms = self._normalize_terms(snapshot.get('topic_terms') or [])
            if topic_terms:
                return topic_terms
        return []

    def _latest_tone_hint(self, uow: UnitOfWork, session_id: str) -> str:
        recent_messages = list(uow.chat_messages.list_by_session(session_id, limit=24))
        for message in reversed(recent_messages):
            if getattr(message, 'role', None) != 'assistant':
                continue
            metadata = getattr(message, 'metadata', {}) or {}
            snapshot = metadata.get('intent_snapshot') or {}
            tone_hint = ' '.join(str(snapshot.get('tone_hint') or '').split()).strip()
            if tone_hint:
                return tone_hint
        return ''

    def _recent_conversation_memory(self, uow: UnitOfWork, session_id: str) -> list[dict[str, object]]:
        rows = list(uow.chat_messages.list_by_session(session_id, limit=12))
        items: list[dict[str, object]] = []
        for message in rows:
            metadata = getattr(message, 'metadata', {}) or {}
            source_type = str(metadata.get('source_type') or message.role or '').strip()
            if source_type == 'search' or getattr(message, 'role', None) == 'search':
                continue
            item: dict[str, object] = {
                'role': getattr(message, 'role', ''),
                'turn_index': getattr(message, 'turn_index', 0),
                'content': self._compact_text(getattr(message, 'content', ''), limit=140),
            }
            if source_type:
                item['source_type'] = source_type
            snapshot = metadata.get('intent_snapshot') or {}
            if isinstance(snapshot, dict) and snapshot:
                item['intent_snapshot'] = {
                    'snapshot_intent': snapshot.get('snapshot_intent'),
                    'topic_terms': self._normalize_terms(snapshot.get('topic_terms') or []),
                    'tone_hint': ' '.join(str(snapshot.get('tone_hint') or '').split()).strip(),
                }
            items.append(item)
        return items[-6:]

    def _session_identity_nodes(self, uow: UnitOfWork, session_id: str) -> list[Node]:
        anchor_keys = ('participant_user', 'participant_assistant', 'participant_search')
        address_hashes = [self._identity_anchor_address(session_id=session_id, anchor_key=key) for key in anchor_keys]
        rows = list(uow.nodes.list_by_address_hashes(address_hashes))
        return [row for row in rows if row is not None]

    def _extract_topic_terms(self, seed_blocks: list[MeaningBlock], seed_nodes: list[ActivatedNode]) -> list[str]:
        tokens: list[str] = []
        for block in seed_blocks:
            self._append_topic_token(tokens, block.normalized_text or block.text)
        for activated in seed_nodes:
            self._append_topic_token(
                tokens,
                getattr(activated.node, 'normalized_value', '') or getattr(activated.node, 'raw_value', ''),
            )
        return tokens[:6]

    def _extract_identity_terms(self, identity_nodes: list[Node]) -> list[str]:
        tokens: list[str] = []
        for node in identity_nodes:
            self._append_topic_token(tokens, node.normalized_value or node.raw_value)
        return tokens[:6]

    def _append_topic_token(self, tokens: list[str], value: str) -> None:
        normalized = ' '.join(str(value or '').split()).strip()
        if len(normalized) < 2 or normalized in tokens:
            return
        tokens.append(normalized)

    def _normalize_terms(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in values or []:
            token = ' '.join(str(item or '').split()).strip()
            if not token or token in normalized:
                continue
            normalized.append(token)
        return normalized[:6]

    def _compact_text(self, value: str, *, limit: int) -> str:
        text = ' '.join(str(value or '').split()).strip()
        if len(text) <= limit:
            return text
        return f'{text[: max(0, limit - 3)]}...'

    def _identity_anchor_address(self, *, session_id: str, anchor_key: str) -> str:
        payload = f'identity_anchor::{session_id}::{anchor_key}'
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()[: self.hash_resolver.digest_size * 2]

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
                # concept 엣지(hierarchy/same-kind/conflict)는 항상 앞으로
                # — max_neighbor_edges 한도에서 relation 엣지에 밀리지 않도록
                1 if edge.edge_family == 'concept' else 0,
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

    def _expand_concept_hops(
        self,
        uow: UnitOfWork,
        *,
        seed_node_ids: list[int],
        existing_edges: list[Edge],
        max_extra_edges: int = 24,
    ) -> list[Edge]:
        """Follow concept edges one additional hop beyond the seed boundary.

        After the first hop, concept-hierarchy nodes appear as edge endpoints but
        their OWN concept connections are not yet fetched.  This method collects
        concept edges for those nodes so that model-asserted concept structure
        (subtype_of, name_variant, etc.) is visible during reasoning.

        Only concept edges are fetched in this pass — relation edges for the
        expanded nodes would add too much noise and are already bounded by the
        seed's own 1-hop expansion.
        """
        seed_id_set = set(seed_node_ids)
        existing_edge_ids: set[int] = {e.id for e in existing_edges if e.id is not None}

        # Concept-adjacent nodes that are NOT seeds (they haven't had their
        # own edges fetched yet).
        concept_node_ids: list[int] = []
        for edge in existing_edges:
            if edge.edge_family != 'concept' or not edge.is_active:
                continue
            for nid in (edge.source_node_id, edge.target_node_id):
                if nid and nid not in seed_id_set and nid not in concept_node_ids:
                    concept_node_ids.append(nid)

        if not concept_node_ids:
            return []

        extra: list[Edge] = []
        for edge in uow.edges.list_edges_for_nodes(concept_node_ids, active_only=True):
            if edge.edge_family != 'concept':
                continue
            if edge.id is None or edge.id in existing_edge_ids:
                continue
            extra.append(edge)
            existing_edge_ids.add(edge.id)
            if len(extra) >= max_extra_edges:
                break

        return extra

    def _seed_score(self, node: Node, block: MeaningBlock, *, reused_via: str | None) -> float:
        base = node.trust_score * 0.45 + node.stability_score * 0.35
        via_bonus = 0.15 if reused_via == 'address_hash' else 0.08
        exact_bonus = 0.05 if (node.normalized_value or '') == block.normalized_text else 0.0
        return round(base + via_bonus + exact_bonus, 6)
