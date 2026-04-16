from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any
from uuid import uuid4
import hashlib

from core.cognition.direct_node_accessor import DirectNodeAccessor
from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.cognition.meaning_block import MeaningBlock
from core.entities.chat_message import ChatMessage
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from core.entities.node_pointer import NodePointer
from core.update.source_trust_policy import SourceTrustPolicy
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
    source_type: str = 'user'
    claim_domain: str | None = None


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
    source_type: str = 'user'
    claim_domain: str = 'general_claim'


class GraphIngestService:
    """MK5 hybrid ingest loop with source-aware trust policy.

    The world graph stays single-layered. New information from user / assistant /
    search sources is inserted into the same graph, but source-specific trust
    profiles determine initial trust and trust growth rates.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        hash_resolver: HashResolver | None = None,
        segmenter: InputSegmenter | None = None,
        accessor: DirectNodeAccessor | None = None,
        trust_policy: SourceTrustPolicy | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.hash_resolver = hash_resolver or HashResolver()
        self.segmenter = segmenter or InputSegmenter(hash_resolver=self.hash_resolver)
        self.accessor = accessor or DirectNodeAccessor(self.hash_resolver)
        self.trust_policy = trust_policy or SourceTrustPolicy()

    def ingest(self, request: GraphIngestRequest) -> GraphIngestResult:
        source_type = request.source_type or str(request.metadata.get('source_type') or request.role or 'unknown')
        claim_domain = request.claim_domain or request.metadata.get('claim_domain') or self.trust_policy.infer_claim_domain(
            request.content,
            source_type=source_type,
        )
        profile = self.trust_policy.profile_for(source_type=source_type, claim_domain=claim_domain)

        blocks = self.segmenter.segment(request.content)
        message_uid = request.message_uid or self._new_uid('msg')
        message_metadata = dict(request.metadata)
        message_metadata.setdefault('source_type', source_type)
        message_metadata.setdefault('claim_domain', claim_domain)

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
                    metadata=message_metadata,
                )
            )
            parsed_input = {
                'sentence_count': len(self.segmenter.split_sentences(request.content)),
                'blocks': [
                    {
                        'block_kind': block.block_kind,
                        'text': block.text,
                        'normalized_text': block.normalized_text,
                        'sentence_index': block.sentence_index,
                    }
                    for block in blocks
                ],
                'source_type': source_type,
                'claim_domain': claim_domain,
            }
            root_event = uow.graph_events.add(
                GraphEvent(
                    event_uid=self._new_uid('evt'),
                    event_type='message_ingested',
                    message_id=message.id,
                    input_text=request.content,
                    parsed_input=parsed_input,
                    effect={
                        'message_uid': message.message_uid,
                        'source_type': source_type,
                        'claim_domain': claim_domain,
                    },
                )
            )

            result = GraphIngestResult(
                message_id=message.id or 0,
                root_event_id=root_event.id or 0,
                message_uid=message.message_uid,
                block_count=len(blocks),
                blocks=blocks,
                source_type=source_type,
                claim_domain=claim_domain,
            )

            resolved: list[tuple[MeaningBlock, Node]] = []
            sentence_nodes: dict[int, dict[int, Node]] = defaultdict(dict)

            for block in blocks:
                lookup = self.accessor.resolve(uow.nodes, block)
                if lookup.node is None:
                    node = uow.nodes.add(
                        Node(
                            node_uid=self._new_uid('node'),
                            address_hash=lookup.address_hash,
                            node_kind='node',
                            raw_value=block.text,
                            normalized_value=block.normalized_text,
                            payload={
                                'source_sentence': block.source_sentence,
                                'source': block.metadata.get('source'),
                                'address_scope': self.hash_resolver.scope_for_block(block),
                                'block_kind': block.block_kind,
                                'sentence_index': block.sentence_index,
                                'block_index': block.block_index,
                                'source_type': source_type,
                                'claim_domain': claim_domain,
                                'source_counts': {source_type: 1},
                            },
                            trust_score=profile.initial_node_trust,
                            stability_score=profile.initial_node_trust,
                            created_from_event_id=root_event.id,
                        )
                    )
                    result.created_node_ids.append(node.id or 0)
                    node_event = uow.graph_events.add(
                        GraphEvent(
                            event_uid=self._new_uid('evt'),
                            event_type='node_created',
                            message_id=message.id,
                            trigger_node_id=node.id,
                            input_text=block.text,
                            parsed_input={
                                'block_kind': block.block_kind,
                                'normalized_text': block.normalized_text,
                                'source_type': source_type,
                                'claim_domain': claim_domain,
                            },
                            effect={
                                'address_hash': lookup.address_hash,
                                'initial_trust': profile.initial_node_trust,
                            },
                            note='Meaning block persisted as durable node.',
                        )
                    )
                    result.created_event_ids.append(node_event.id or 0)
                else:
                    node = lookup.node
                    result.reused_node_ids.append(node.id or 0)
                    self._update_reused_node(uow, node, source_type=source_type, claim_domain=claim_domain, profile=profile)
                    node_event = uow.graph_events.add(
                        GraphEvent(
                            event_uid=self._new_uid('evt'),
                            event_type='node_supported',
                            message_id=message.id,
                            trigger_node_id=node.id,
                            input_text=block.text,
                            parsed_input={
                                'block_kind': block.block_kind,
                                'normalized_text': block.normalized_text,
                                'source_type': source_type,
                                'claim_domain': claim_domain,
                            },
                            effect={
                                'trust_delta': profile.node_reuse_trust_delta,
                            },
                            note='Existing node reinforced by repeated evidence.',
                        )
                    )
                    result.created_event_ids.append(node_event.id or 0)

                resolved.append((block, node))
                sentence_nodes[block.sentence_index][node.id or 0] = node

            identity_anchor = self._ensure_identity_anchor(
                uow=uow,
                session_id=request.session_id,
                role=request.role,
                source_type=source_type,
                claim_domain=claim_domain,
                root_event_id=root_event.id,
                message_id=message.id,
            )
            if identity_anchor is not None:
                if identity_anchor.id is not None and identity_anchor.id not in result.reused_node_ids and identity_anchor.id not in result.created_node_ids:
                    result.reused_node_ids.append(identity_anchor.id)
                self._link_identity_anchor(
                    uow=uow,
                    anchor_node=identity_anchor,
                    resolved=resolved,
                    message=message,
                    root_event=root_event,
                    result=result,
                    session_id=request.session_id,
                    source_type=source_type,
                    claim_domain=claim_domain,
                    profile=profile,
                )

            self._link_sentence_co_occurrence(
                uow=uow,
                message=message,
                root_event=root_event,
                sentence_nodes=sentence_nodes,
                result=result,
                source_type=source_type,
                claim_domain=claim_domain,
                profile=profile,
            )
            self._create_partial_reuse_pointers(
                uow=uow,
                message=message,
                root_event=root_event,
                resolved=resolved,
                result=result,
                source_type=source_type,
                claim_domain=claim_domain,
            )
            uow.commit()
            return result

    def _update_reused_node(
        self,
        uow: UnitOfWork,
        node: Node,
        *,
        source_type: str,
        claim_domain: str,
        profile,
    ) -> None:
        payload = dict(node.payload or {})
        source_counts = dict(payload.get('source_counts') or {})
        source_counts[source_type] = int(source_counts.get(source_type, 0)) + 1
        payload['source_counts'] = source_counts
        payload['last_source_type'] = source_type
        payload['last_claim_domain'] = claim_domain
        uow.nodes.update_payload(node.id or 0, payload)
        new_trust = self.trust_policy.clamp_trust(node.trust_score + profile.node_reuse_trust_delta)
        new_stability = self.trust_policy.clamp_trust(node.stability_score + (profile.node_reuse_trust_delta / 2))
        uow.nodes.update_scores(node.id or 0, trust_score=new_trust, stability_score=new_stability)

    def _link_sentence_co_occurrence(
        self,
        *,
        uow: UnitOfWork,
        message: ChatMessage,
        root_event: GraphEvent,
        sentence_nodes: dict[int, dict[int, Node]],
        result: GraphIngestResult,
        source_type: str,
        claim_domain: str,
        profile,
    ) -> None:
        for sentence_index, node_map in sentence_nodes.items():
            if len(node_map) < 2:
                continue
            for source_id, target_id in combinations(sorted(node_map), 2):
                existing = uow.edges.find_active_relation(
                    source_id,
                    target_id,
                    edge_family='relation',
                    connect_type='neutral',
                )
                if existing is None:
                    edge = uow.edges.add(
                        Edge(
                            edge_uid=self._new_uid('edge'),
                            source_node_id=source_id,
                            target_node_id=target_id,
                            edge_family='relation',
                            connect_type='neutral',
                            relation_detail={
                                'scope': 'sentence',
                                'note': 'Weak same-sentence co-occurrence relation.',
                                'sentence_index': sentence_index,
                                'message_id': message.id,
                                'source_type': source_type,
                                'claim_domain': claim_domain,
                                'source_counts': {source_type: 1},
                            },
                            edge_weight=profile.edge_weight,
                            trust_score=profile.initial_edge_trust,
                            support_count=1,
                            created_from_event_id=root_event.id,
                        )
                    )
                    result.created_edge_ids.append(edge.id or 0)
                    edge_event = uow.graph_events.add(
                        GraphEvent(
                            event_uid=self._new_uid('evt'),
                            event_type='edge_created',
                            message_id=message.id,
                            trigger_edge_id=edge.id,
                            parsed_input={
                                'sentence_index': sentence_index,
                                'source_type': source_type,
                                'claim_domain': claim_domain,
                            },
                            effect={
                                'edge_family': 'relation',
                                'connect_type': 'neutral',
                                'source_node_id': source_id,
                                'target_node_id': target_id,
                                'initial_trust': profile.initial_edge_trust,
                            },
                            note='Weak same-sentence co-occurrence relation created.',
                        )
                    )
                    result.created_event_ids.append(edge_event.id or 0)
                else:
                    relation_detail = dict(existing.relation_detail or {})
                    source_counts = dict(relation_detail.get('source_counts') or {})
                    source_counts[source_type] = int(source_counts.get(source_type, 0)) + 1
                    relation_detail['source_counts'] = source_counts
                    relation_detail['last_source_type'] = source_type
                    relation_detail['last_claim_domain'] = claim_domain
                    uow.edges.update_relation_detail(existing.id or 0, relation_detail)
                    uow.edges.bump_support(existing.id or 0, delta=1, trust_delta=profile.edge_support_trust_delta)
                    result.supported_edge_ids.append(existing.id or 0)
                    support_event = uow.graph_events.add(
                        GraphEvent(
                            event_uid=self._new_uid('evt'),
                            event_type='edge_supported',
                            message_id=message.id,
                            trigger_edge_id=existing.id,
                            parsed_input={
                                'sentence_index': sentence_index,
                                'source_type': source_type,
                                'claim_domain': claim_domain,
                            },
                            effect={'delta': 1, 'trust_delta': profile.edge_support_trust_delta},
                            note='Existing co-occurrence relation reinforced.',
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
        source_type: str,
        claim_domain: str,
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
                    'partial_reuse',
                    pointer_slot='contained_block',
                )
                if existing is not None:
                    continue
                pointer = uow.node_pointers.add(
                    NodePointer(
                        pointer_uid=self._new_uid('ptr'),
                        owner_node_id=longer[1].id or 0,
                        referenced_node_id=shorter[1].id or 0,
                        pointer_type='partial_reuse',
                        pointer_slot='contained_block',
                        detail={
                            'sentence_index': sentence_index,
                            'owner_text': longer[0].normalized_text,
                            'referenced_text': shorter[0].normalized_text,
                            'source_type': source_type,
                            'claim_domain': claim_domain,
                        },
                        created_from_event_id=root_event.id,
                    )
                )
                result.created_pointer_ids.append(pointer.id or 0)
                pointer_event = uow.graph_events.add(
                    GraphEvent(
                        event_uid=self._new_uid('evt'),
                        event_type='pointer_created',
                        message_id=message.id,
                        trigger_node_id=longer[1].id,
                        input_text=longer[0].text,
                        parsed_input={
                            'sentence_index': sentence_index,
                            'source_type': source_type,
                            'claim_domain': claim_domain,
                        },
                        effect={'referenced_node_id': shorter[1].id, 'pointer_type': 'partial_reuse'},
                        note='Contained meaning block reused through node pointer.',
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

    def _ensure_identity_anchor(
        self,
        *,
        uow: UnitOfWork,
        session_id: str,
        role: str,
        source_type: str,
        claim_domain: str,
        root_event_id: int | None,
        message_id: int | None,
    ) -> Node | None:
        anchor_key = self._identity_anchor_key(role=role, source_type=source_type)
        if not anchor_key:
            return None
        address_hash = self._identity_anchor_address(session_id=session_id, anchor_key=anchor_key)
        existing = uow.nodes.get_by_address_hash(address_hash)
        if existing is not None:
            payload = dict(existing.payload or {})
            payload['last_source_type'] = source_type
            payload['last_claim_domain'] = claim_domain
            payload['session_id'] = session_id
            payload['anchor_key'] = anchor_key
            uow.nodes.update_payload(existing.id or 0, payload)
            return existing

        anchor = uow.nodes.add(
            Node(
                node_uid=self._new_uid('node'),
                address_hash=address_hash,
                node_kind='node',
                raw_value=anchor_key,
                normalized_value=anchor_key,
                payload={
                    'session_id': session_id,
                    'anchor_key': anchor_key,
                    'source_type': source_type,
                    'claim_domain': claim_domain,
                    'created_from_message_id': message_id,
                },
                trust_score=0.9,
                stability_score=0.9,
                created_from_event_id=root_event_id,
            )
        )
        uow.graph_events.add(
            GraphEvent(
                event_uid=self._new_uid('evt'),
                event_type='identity_anchor_created',
                message_id=message_id,
                trigger_node_id=anchor.id,
                parsed_input={
                    'session_id': session_id,
                    'anchor_key': anchor_key,
                    'source_type': source_type,
                },
                effect={'address_hash': address_hash},
                note='Session-scoped identity anchor node created.',
            )
        )
        return anchor

    def _link_identity_anchor(
        self,
        *,
        uow: UnitOfWork,
        anchor_node: Node,
        resolved: list[tuple[MeaningBlock, Node]],
        message: ChatMessage,
        root_event: GraphEvent,
        result: GraphIngestResult,
        session_id: str,
        source_type: str,
        claim_domain: str,
        profile,
    ) -> None:
        seen_target_ids: set[int] = set()
        for _block, node in resolved:
            if node.id is None or anchor_node.id is None or node.id == anchor_node.id or node.id in seen_target_ids:
                continue
            seen_target_ids.add(node.id)
            existing = uow.edges.find_active_relation(
                anchor_node.id,
                node.id,
                edge_family='relation',
                connect_type='flow',
            )
            if existing is None:
                edge = uow.edges.add(
                    Edge(
                        edge_uid=self._new_uid('edge'),
                        source_node_id=anchor_node.id,
                        target_node_id=node.id,
                        edge_family='relation',
                        connect_type='flow',
                        relation_detail={
                            'message_id': message.id,
                            'turn_index': message.turn_index,
                            'session_id': session_id,
                            'source_type': source_type,
                            'claim_domain': claim_domain,
                            'anchor_key': anchor_node.normalized_value,
                            'scope': 'session_temporary',
                            'temporary_edge': True,
                            'temporary_kind': 'identity_anchor_binding',
                            'temporary_policy': 'clear_on_topic_shift',
                            'note': 'Session identity anchor linked to message-derived node.',
                            'source_counts': {source_type: 1},
                        },
                        edge_weight=max(0.15, profile.edge_weight),
                        trust_score=profile.initial_edge_trust,
                        support_count=1,
                        created_from_event_id=root_event.id,
                    )
                )
                result.created_edge_ids.append(edge.id or 0)
                event = uow.graph_events.add(
                    GraphEvent(
                        event_uid=self._new_uid('evt'),
                        event_type='identity_anchor_linked',
                        message_id=message.id,
                        trigger_edge_id=edge.id,
                        parsed_input={
                            'source_type': source_type,
                            'claim_domain': claim_domain,
                            'anchor_node_id': anchor_node.id,
                            'target_node_id': node.id,
                        },
                        effect={
                            'edge_family': 'relation',
                            'connect_type': 'flow',
                        },
                        note='Identity anchor linked to message-derived node.',
                    )
                )
                result.created_event_ids.append(event.id or 0)
            else:
                relation_detail = dict(existing.relation_detail or {})
                source_counts = dict(relation_detail.get('source_counts') or {})
                source_counts[source_type] = int(source_counts.get(source_type, 0)) + 1
                relation_detail['source_counts'] = source_counts
                relation_detail['last_message_id'] = message.id
                relation_detail['last_turn_index'] = message.turn_index
                relation_detail['last_claim_domain'] = claim_domain
                relation_detail['session_id'] = session_id
                relation_detail['scope'] = 'session_temporary'
                relation_detail['temporary_edge'] = True
                relation_detail['temporary_kind'] = 'identity_anchor_binding'
                relation_detail['temporary_policy'] = 'clear_on_topic_shift'
                uow.edges.update_relation_detail(existing.id or 0, relation_detail)
                uow.edges.bump_support(existing.id or 0, delta=1, trust_delta=profile.edge_support_trust_delta)
                result.supported_edge_ids.append(existing.id or 0)

    def _identity_anchor_key(self, *, role: str, source_type: str) -> str:
        normalized_role = ' '.join(str(role or '').split()).strip().lower()
        normalized_source = ' '.join(str(source_type or '').split()).strip().lower()
        if normalized_role == 'user' or normalized_source == 'user':
            return 'participant_user'
        if normalized_role == 'assistant' or normalized_source == 'assistant':
            return 'participant_assistant'
        if normalized_role == 'search' or normalized_source == 'search':
            return 'participant_search'
        return ''

    def _identity_anchor_address(self, *, session_id: str, anchor_key: str) -> str:
        payload = f'identity_anchor::{session_id}::{anchor_key}'
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()[: self.hash_resolver.digest_size * 2]

    def _new_uid(self, prefix: str) -> str:
        return f'{prefix}-{uuid4().hex}'
