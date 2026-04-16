from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.entities.edge import Edge
from storage.unit_of_work import UnitOfWork

REVISION_PURPOSE = 'revision'
REVISION_KIND_CONFLICT_ASSERTION = 'conflict_assertion'
REVISION_KIND_PENDING = 'revision_pending'
REVISION_KIND_DEACTIVATE_CANDIDATE = 'deactivate_candidate'
REVISION_KIND_MERGE_CANDIDATE = 'merge_candidate'


@dataclass(slots=True)
class RevisionEdgeUpsertResult:
    edge_id: int | None
    action: str


@dataclass(slots=True)
class RevisionEdgeService:
    max_reasons: int = 12

    def record_conflict_assertion(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        reason: str,
        signal_score: float,
        message_id: int | None,
    ) -> RevisionEdgeUpsertResult:
        relation_detail = self._base_detail(
            kind=REVISION_KIND_CONFLICT_ASSERTION,
            reason=reason,
            message_id=message_id,
            source_edge_id=base_edge.id,
            signal_score=signal_score,
        )
        return self._upsert_revision_edge(
            uow,
            base_edge=base_edge,
            connect_type='conflict',
            relation_detail=relation_detail,
            initial_trust=max(0.35, min(0.95, signal_score)),
            trust_delta=max(0.02, signal_score * 0.05),
        )

    def record_revision_marker(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        kind: str,
        reason: str,
        message_id: int | None,
        status: str = 'open',
        metadata: dict[str, Any] | None = None,
    ) -> RevisionEdgeUpsertResult:
        relation_detail = self._base_detail(
            kind=kind,
            reason=reason,
            message_id=message_id,
            source_edge_id=base_edge.id,
        )
        relation_detail['status'] = status
        if metadata:
            relation_detail['metadata'] = dict(metadata)
        return self._upsert_revision_edge(
            uow,
            base_edge=base_edge,
            connect_type='neutral',
            relation_detail=relation_detail,
            initial_trust=max(0.3, min(0.85, base_edge.trust_score * 0.9)),
            trust_delta=0.01,
        )

    def _upsert_revision_edge(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        connect_type: str,
        relation_detail: dict[str, Any],
        initial_trust: float,
        trust_delta: float,
    ) -> RevisionEdgeUpsertResult:
        existing = self._find_existing_revision_edge(
            uow,
            base_edge=base_edge,
            connect_type=connect_type,
            kind=str(relation_detail.get('kind') or ''),
        )
        if existing is None:
            created = uow.edges.add(
                Edge(
                    edge_uid=f'revision-{uuid4().hex}',
                    source_node_id=base_edge.source_node_id,
                    target_node_id=base_edge.target_node_id,
                    edge_family=base_edge.edge_family,
                    connect_type=connect_type,
                    relation_detail=relation_detail,
                    edge_weight=max(0.1, base_edge.edge_weight),
                    trust_score=initial_trust,
                    support_count=1,
                    created_from_event_id=base_edge.created_from_event_id,
                )
            )
            return RevisionEdgeUpsertResult(edge_id=created.id, action='created')

        merged_detail = self._merge_detail(
            existing.relation_detail,
            relation_detail,
        )
        if existing.id is not None:
            uow.edges.update_relation_detail(existing.id, merged_detail)
            uow.edges.bump_support(existing.id, delta=1, trust_delta=trust_delta)
        return RevisionEdgeUpsertResult(edge_id=existing.id, action='supported')

    def _find_existing_revision_edge(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        connect_type: str,
        kind: str,
    ) -> Edge | None:
        candidates = uow.edges.list_outgoing(
            base_edge.source_node_id,
            edge_families=[base_edge.edge_family],
            connect_types=[connect_type],
            active_only=True,
        )
        for edge in candidates:
            if edge.target_node_id != base_edge.target_node_id:
                continue
            detail = dict(edge.relation_detail or {})
            if detail.get('purpose') != REVISION_PURPOSE:
                continue
            if str(detail.get('kind') or '') != kind:
                continue
            return edge
        return None

    def _base_detail(
        self,
        *,
        kind: str,
        reason: str,
        message_id: int | None,
        source_edge_id: int | None,
        signal_score: float | None = None,
    ) -> dict[str, Any]:
        reasons = [reason] if reason else []
        detail: dict[str, Any] = {
            'purpose': REVISION_PURPOSE,
            'kind': kind,
            'status': 'open',
            'source_edge_ids': [source_edge_id] if source_edge_id is not None else [],
            'reasons': reasons,
            'latest_reason': reason,
            'created_from_message_id': message_id,
            'last_message_id': message_id,
        }
        if signal_score is not None:
            detail['latest_signal_score'] = signal_score
        return detail

    def _merge_detail(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current = dict(existing or {})
        new = dict(incoming or {})
        reasons = list(current.get('reasons') or [])
        for item in list(new.get('reasons') or []):
            token = str(item or '').strip()
            if token and token not in reasons:
                reasons.append(token)
        source_edge_ids = list(current.get('source_edge_ids') or [])
        for item in list(new.get('source_edge_ids') or []):
            try:
                edge_id = int(item)
            except (TypeError, ValueError):
                continue
            if edge_id not in source_edge_ids:
                source_edge_ids.append(edge_id)

        merged = current
        merged.update(new)
        merged['reasons'] = reasons[-self.max_reasons:]
        merged['source_edge_ids'] = source_edge_ids
        if not merged.get('latest_reason'):
            merged['latest_reason'] = reasons[-1] if reasons else ''
        return merged
