from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.cognition.hash_resolver import HashResolver
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class TemporaryEdgeCleanupResult:
    attempted: bool
    triggered: bool
    topic_continuity: str
    topic_overlap_count: int
    deactivated_edge_ids: list[int] = field(default_factory=list)
    reason: str = ''

    def to_debug(self) -> dict[str, Any]:
        return {
            'attempted': self.attempted,
            'triggered': self.triggered,
            'topic_continuity': self.topic_continuity,
            'topic_overlap_count': self.topic_overlap_count,
            'deactivated_count': len(self.deactivated_edge_ids),
            'deactivated_edge_ids': list(self.deactivated_edge_ids),
            'reason': self.reason,
        }


@dataclass(slots=True)
class TemporaryEdgeService:
    hash_resolver: HashResolver = field(default_factory=HashResolver)

    def cleanup_on_topic_shift(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        session_id: str,
        current_turn_index: int,
        intent_snapshot: dict[str, Any] | None,
    ) -> TemporaryEdgeCleanupResult:
        snapshot = dict(intent_snapshot or {})
        topic_continuity = ' '.join(str(snapshot.get('topic_continuity') or '').split()).strip()
        topic_overlap_count = int(snapshot.get('topic_overlap_count') or 0)
        shifted = bool(snapshot.get('shifted'))
        if not shifted or topic_overlap_count != 0:
            return TemporaryEdgeCleanupResult(
                attempted=True,
                triggered=False,
                topic_continuity=topic_continuity or 'unknown',
                topic_overlap_count=topic_overlap_count,
                reason='shift_cleanup_not_triggered',
            )

        deactivated_edge_ids: list[int] = []
        with uow_factory() as uow:
            anchor_ids = self._session_identity_anchor_ids(uow, session_id=session_id)
            for anchor_id in anchor_ids:
                for edge in uow.edges.list_outgoing(anchor_id, edge_families=['relation'], active_only=True):
                    if edge.id is None:
                        continue
                    detail = dict(edge.relation_detail or {})
                    if not self._is_session_temporary_edge(detail=detail, session_id=session_id):
                        continue
                    detail['temporary_deactivated_reason'] = 'topic_shifted'
                    detail['temporary_deactivated_turn_index'] = current_turn_index
                    uow.edges.update_relation_detail(edge.id, detail)
                    uow.edges.deactivate(edge.id)
                    deactivated_edge_ids.append(edge.id)
            uow.commit()

        return TemporaryEdgeCleanupResult(
            attempted=True,
            triggered=True,
            topic_continuity=topic_continuity,
            topic_overlap_count=topic_overlap_count,
            deactivated_edge_ids=deactivated_edge_ids,
            reason='shift_cleanup_executed',
        )

    def _session_identity_anchor_ids(self, uow: UnitOfWork, *, session_id: str) -> list[int]:
        anchor_keys = ('participant_user', 'participant_assistant', 'participant_search')
        address_hashes = [self._identity_anchor_address(session_id=session_id, anchor_key=key) for key in anchor_keys]
        rows = list(uow.nodes.list_by_address_hashes(address_hashes))
        return [row.id for row in rows if row is not None and row.id is not None]

    def _identity_anchor_address(self, *, session_id: str, anchor_key: str) -> str:
        payload = f'identity_anchor::{session_id}::{anchor_key}'
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()[: self.hash_resolver.digest_size * 2]

    def _is_session_temporary_edge(self, *, detail: dict[str, Any], session_id: str) -> bool:
        if not bool(detail.get('temporary_edge')):
            return False
        if str(detail.get('scope') or '').strip() != 'session_temporary':
            return False
        edge_session = str(detail.get('session_id') or '').strip()
        return edge_session == session_id

