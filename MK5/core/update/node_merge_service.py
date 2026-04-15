from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from core.update.pointer_rewrite_service import PointerRewriteService
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class NodeMergeRequest:
    canonical_node_id: int
    absorbed_node_ids: list[int]
    message_id: int | None = None
    merge_reason: str = 'manual_merge'
    note: str | None = None


@dataclass(slots=True)
class NodeMergeResult:
    canonical_node_id: int
    absorbed_node_ids: list[int]
    rewired_edge_ids: list[int] = field(default_factory=list)
    merged_edge_ids: list[int] = field(default_factory=list)
    deactivated_edge_ids: list[int] = field(default_factory=list)
    rewired_pointer_ids: list[int] = field(default_factory=list)
    merged_pointer_ids: list[int] = field(default_factory=list)
    deactivated_pointer_ids: list[int] = field(default_factory=list)
    deactivated_node_ids: list[int] = field(default_factory=list)
    created_event_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class NodeMergeService:
    uow_factory: callable
    pointer_rewrite_service: PointerRewriteService = field(default_factory=PointerRewriteService)

    def merge(self, request: NodeMergeRequest) -> NodeMergeResult:
        with self.uow_factory() as uow:
            result = self.merge_with_uow(uow, request)
            uow.commit()
            return result

    def merge_with_uow(self, uow: UnitOfWork, request: NodeMergeRequest) -> NodeMergeResult:
        absorbed_ids = [node_id for node_id in request.absorbed_node_ids if node_id != request.canonical_node_id]
        result = NodeMergeResult(
            canonical_node_id=request.canonical_node_id,
            absorbed_node_ids=list(absorbed_ids),
        )
        if not absorbed_ids:
            return result

        canonical = self._require_active_node(uow, request.canonical_node_id)
        canonical_payload = dict(canonical.payload or {})
        canonical_trust = canonical.trust_score
        canonical_stability = canonical.stability_score

        for absorbed_id in absorbed_ids:
            absorbed = self._require_active_node(uow, absorbed_id)

            edge_result = self._rewrite_edges(
                uow=uow,
                merged_node_id=absorbed.id or 0,
                canonical_node_id=canonical.id or 0,
            )
            result.rewired_edge_ids.extend(edge_result['rewired'])
            result.merged_edge_ids.extend(edge_result['merged'])
            result.deactivated_edge_ids.extend(edge_result['deactivated'])

            pointer_result = self.pointer_rewrite_service.rewrite_for_node_merge(
                uow=uow,
                merged_node_id=absorbed.id or 0,
                canonical_node_id=canonical.id or 0,
            )
            result.rewired_pointer_ids.extend(pointer_result.rewired_pointer_ids)
            result.merged_pointer_ids.extend(pointer_result.merged_pointer_ids)
            result.deactivated_pointer_ids.extend(pointer_result.deactivated_pointer_ids)

            canonical_payload = self._merge_node_payload(canonical_payload, absorbed)
            canonical_trust = max(canonical_trust, absorbed.trust_score)
            canonical_stability = max(canonical_stability, absorbed.stability_score)

            uow.nodes.deactivate(absorbed.id or 0, revision_state='merged')
            result.deactivated_node_ids.append(absorbed.id or 0)

            event = uow.graph_events.add(
                GraphEvent(
                    event_uid=self._new_uid('evt'),
                    event_type='node_merged',
                    message_id=request.message_id,
                    trigger_node_id=canonical.id,
                    parsed_input={
                        'canonical_node_id': canonical.id,
                        'absorbed_node_id': absorbed.id,
                        'merge_reason': request.merge_reason,
                    },
                    effect={
                        'rewired_edge_ids': list(edge_result['rewired']),
                        'merged_edge_ids': list(edge_result['merged']),
                        'deactivated_edge_ids': list(edge_result['deactivated']),
                        'rewired_pointer_ids': list(pointer_result.rewired_pointer_ids),
                        'merged_pointer_ids': list(pointer_result.merged_pointer_ids),
                        'deactivated_pointer_ids': list(pointer_result.deactivated_pointer_ids),
                    },
                    note=request.note or 'Node absorbed into canonical concept node.',
                )
            )
            result.created_event_ids.append(event.id or 0)

        uow.nodes.update_payload(canonical.id or 0, canonical_payload)
        uow.nodes.update_scores(
            canonical.id or 0,
            trust_score=canonical_trust,
            stability_score=canonical_stability,
            revision_state='stable',
        )
        return result

    def _rewrite_edges(
        self,
        *,
        uow: UnitOfWork,
        merged_node_id: int,
        canonical_node_id: int,
    ) -> dict[str, list[int]]:
        rewired: list[int] = []
        merged: list[int] = []
        deactivated: list[int] = []
        processed: set[int] = set()

        for edge in list(uow.edges.list_outgoing(merged_node_id, active_only=True)):
            if edge.id is None or edge.id in processed:
                continue
            processed.add(edge.id)
            action = self._rewrite_single_edge(
                uow=uow,
                edge_id=edge.id,
                current_source=edge.source_node_id,
                current_target=edge.target_node_id,
                new_source=canonical_node_id,
                new_target=edge.target_node_id,
                merged_node_id=merged_node_id,
                canonical_node_id=canonical_node_id,
                edge_type=edge.edge_type,
            )
            rewired.extend(action['rewired'])
            merged.extend(action['merged'])
            deactivated.extend(action['deactivated'])

        for edge in list(uow.edges.list_incoming(merged_node_id, active_only=True)):
            if edge.id is None or edge.id in processed:
                continue
            processed.add(edge.id)
            action = self._rewrite_single_edge(
                uow=uow,
                edge_id=edge.id,
                current_source=edge.source_node_id,
                current_target=edge.target_node_id,
                new_source=edge.source_node_id,
                new_target=canonical_node_id,
                merged_node_id=merged_node_id,
                canonical_node_id=canonical_node_id,
                edge_type=edge.edge_type,
            )
            rewired.extend(action['rewired'])
            merged.extend(action['merged'])
            deactivated.extend(action['deactivated'])

        return {'rewired': rewired, 'merged': merged, 'deactivated': deactivated}

    def _rewrite_single_edge(
        self,
        *,
        uow: UnitOfWork,
        edge_id: int,
        current_source: int,
        current_target: int,
        new_source: int,
        new_target: int,
        merged_node_id: int,
        canonical_node_id: int,
        edge_type: str,
    ) -> dict[str, list[int]]:
        edge = uow.edges.get_by_id(edge_id)
        if edge is None or not edge.is_active:
            return {'rewired': [], 'merged': [], 'deactivated': []}
        if new_source == new_target:
            uow.edges.deactivate(edge_id)
            return {'rewired': [], 'merged': [], 'deactivated': [edge_id]}

        duplicate = uow.edges.find_active_relation(new_source, new_target, edge_type)
        if duplicate is not None and duplicate.id != edge_id:
            merged_detail = self._merge_relation_detail(duplicate.relation_detail, edge.relation_detail, merged_edge_id=edge_id)
            uow.edges.update_relation_detail(duplicate.id or 0, merged_detail)
            uow.edges.update_counters(
                duplicate.id or 0,
                support_count=duplicate.support_count + edge.support_count,
                conflict_count=duplicate.conflict_count + edge.conflict_count,
            )
            uow.edges.update_scores(
                duplicate.id or 0,
                edge_weight=max(duplicate.edge_weight, edge.edge_weight),
                trust_score=max(duplicate.trust_score, edge.trust_score),
                contradiction_pressure=max(duplicate.contradiction_pressure, edge.contradiction_pressure),
            )
            uow.edges.deactivate(edge_id)
            return {'rewired': [], 'merged': [edge_id], 'deactivated': []}

        updated_detail = self._annotate_edge_detail(
            edge.relation_detail,
            merged_node_id=merged_node_id,
            canonical_node_id=canonical_node_id,
        )
        uow.edges.reassign(edge_id, source_node_id=new_source, target_node_id=new_target)
        uow.edges.update_relation_detail(edge_id, updated_detail)
        return {'rewired': [edge_id], 'merged': [], 'deactivated': []}

    def _merge_node_payload(self, canonical_payload: dict[str, Any], absorbed: Node) -> dict[str, Any]:
        merged = dict(canonical_payload or {})
        absorbed_payload = dict(absorbed.payload or {})

        source_counts = dict(merged.get('source_counts') or {})
        for source_type, count in dict(absorbed_payload.get('source_counts') or {}).items():
            source_counts[source_type] = int(source_counts.get(source_type, 0)) + int(count)
        if source_counts:
            merged['source_counts'] = source_counts

        merged_from = list(merged.get('merged_from') or [])
        merged_from.append(
            {
                'node_id': absorbed.id,
                'node_uid': absorbed.node_uid,
                'address_hash': absorbed.address_hash,
                'normalized_value': absorbed.normalized_value,
            }
        )
        merged['merged_from'] = merged_from

        aliases = list(merged.get('raw_aliases') or [])
        for candidate in (absorbed.raw_value, absorbed.normalized_value):
            if candidate and candidate not in aliases:
                aliases.append(candidate)
        if aliases:
            merged['raw_aliases'] = aliases

        for key, value in absorbed_payload.items():
            if key in {'source_counts'}:
                continue
            if key not in merged:
                merged[key] = value
                continue
            if merged[key] == value:
                continue
            collisions = dict(merged.get('merged_payload_values') or {})
            existing_values = list(collisions.get(key) or [])
            for candidate in (merged[key], value):
                if candidate not in existing_values:
                    existing_values.append(candidate)
            collisions[key] = existing_values
            merged['merged_payload_values'] = collisions
        return merged

    def _annotate_edge_detail(
        self,
        relation_detail: dict[str, Any],
        *,
        merged_node_id: int,
        canonical_node_id: int,
    ) -> dict[str, Any]:
        updated = dict(relation_detail or {})
        history = list(updated.get('rewrite_history') or [])
        history.append({'from_node_id': merged_node_id, 'to_node_id': canonical_node_id})
        updated['rewrite_history'] = history
        return updated

    def _merge_relation_detail(
        self,
        existing_detail: dict[str, Any],
        absorbed_detail: dict[str, Any],
        *,
        merged_edge_id: int,
    ) -> dict[str, Any]:
        merged = dict(existing_detail or {})
        source_counts = dict(merged.get('source_counts') or {})
        for source_type, count in dict((absorbed_detail or {}).get('source_counts') or {}).items():
            source_counts[source_type] = int(source_counts.get(source_type, 0)) + int(count)
        if source_counts:
            merged['source_counts'] = source_counts

        merged_edge_ids = list(merged.get('merged_edge_ids') or [])
        if merged_edge_id not in merged_edge_ids:
            merged_edge_ids.append(merged_edge_id)
        merged['merged_edge_ids'] = merged_edge_ids

        for key, value in (absorbed_detail or {}).items():
            if key == 'source_counts':
                continue
            if key not in merged:
                merged[key] = value
                continue
            if merged[key] == value:
                continue
            collisions = dict(merged.get('merged_values') or {})
            existing_values = list(collisions.get(key) or [])
            for candidate in (merged[key], value):
                if candidate not in existing_values:
                    existing_values.append(candidate)
            collisions[key] = existing_values
            merged['merged_values'] = collisions
        return merged

    def _require_active_node(self, uow: UnitOfWork, node_id: int) -> Node:
        node = uow.nodes.get_by_id(node_id)
        if node is None:
            raise ValueError(f'Node {node_id} does not exist')
        if not node.is_active:
            raise ValueError(f'Node {node_id} is inactive and cannot participate in merge')
        return node

    def _new_uid(self, prefix: str) -> str:
        return f'{prefix}-{uuid4().hex}'
