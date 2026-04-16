from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from config import CONNECT_TYPE_PROMOTION_MAX_SCAN, CONNECT_TYPE_PROMOTION_THRESHOLD
from core.entities.graph_event import GraphEvent
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class ConnectTypePromotion:
    proposed_connect_type: str
    promoted_edge_ids: list[int] = field(default_factory=list)
    merged_into_existing_edge_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ConnectTypePromotionResult:
    attempted: bool
    promotions: list[ConnectTypePromotion] = field(default_factory=list)
    scanned_edge_count: int = 0

    def to_debug(self) -> dict[str, Any]:
        return {
            'attempted': self.attempted,
            'scanned_edge_count': self.scanned_edge_count,
            'promotion_count': len(self.promotions),
            'promotions': [
                {
                    'proposed_connect_type': item.proposed_connect_type,
                    'promoted_edge_ids': item.promoted_edge_ids,
                    'merged_into_existing_edge_ids': item.merged_into_existing_edge_ids,
                }
                for item in self.promotions
            ],
        }


@dataclass(slots=True)
class ConnectTypePromotionService:
    threshold: int = CONNECT_TYPE_PROMOTION_THRESHOLD
    max_scan: int = CONNECT_TYPE_PROMOTION_MAX_SCAN

    def promote(self, uow: UnitOfWork, *, message_id: int | None = None) -> ConnectTypePromotionResult:
        edges = list(uow.edges.list_active_with_proposed_connect_type(limit=self.max_scan))
        if not edges:
            return ConnectTypePromotionResult(attempted=False, scanned_edge_count=0)

        by_candidate: dict[str, list] = defaultdict(list)
        for edge in edges:
            candidate = self._candidate(edge.relation_detail)
            if candidate:
                by_candidate[candidate].append(edge)

        promotions: list[ConnectTypePromotion] = []
        for candidate, candidate_edges in by_candidate.items():
            evidence_score = sum(self._edge_evidence_score(edge) for edge in candidate_edges)
            if evidence_score < float(self.threshold):
                continue
            promotions.append(
                self._promote_candidate(
                    uow,
                    candidate=candidate,
                    edges=candidate_edges,
                    evidence_score=evidence_score,
                    message_id=message_id,
                )
            )

        return ConnectTypePromotionResult(
            attempted=True,
            promotions=promotions,
            scanned_edge_count=len(edges),
        )

    def _promote_candidate(
        self,
        uow: UnitOfWork,
        *,
        candidate: str,
        edges: list,
        evidence_score: float,
        message_id: int | None,
    ) -> ConnectTypePromotion:
        result = ConnectTypePromotion(proposed_connect_type=candidate)
        for edge in edges:
            if edge.id is None:
                continue
            existing = uow.edges.find_active_relation(
                edge.source_node_id,
                edge.target_node_id,
                edge_family=edge.edge_family,
                connect_type=candidate,
            )
            if existing is not None and existing.id is not None and existing.id != edge.id:
                uow.edges.bump_support(
                    existing.id,
                    delta=max(1, edge.support_count),
                    trust_delta=max(0.02, edge.trust_score * 0.02),
                )
                uow.edges.deactivate(edge.id)
                result.merged_into_existing_edge_ids.append(existing.id)
                continue

            detail = dict(edge.relation_detail or {})
            detail.pop('proposed_connect_type', None)
            detail.pop('proposal_reason', None)
            detail['connect_type_promoted_from'] = edge.connect_type
            detail['connect_type_promoted_reason'] = 'candidate_threshold_met'
            uow.edges.update_connect_type(
                edge.id,
                connect_type=candidate,
                relation_detail=detail,
            )
            result.promoted_edge_ids.append(edge.id)

        if result.promoted_edge_ids or result.merged_into_existing_edge_ids:
            uow.graph_events.add(
                GraphEvent(
                    event_uid=f'evt-{uuid4().hex}',
                    event_type='connect_type_promoted',
                    message_id=message_id,
                    parsed_input={
                        'candidate': candidate,
                        'threshold': self.threshold,
                        'edge_count': len(edges),
                        'evidence_score': round(evidence_score, 6),
                    },
                    effect={
                        'promoted_edge_ids': result.promoted_edge_ids,
                        'merged_into_existing_edge_ids': result.merged_into_existing_edge_ids,
                    },
                    note='Proposed connect type promoted after repeated model assertions.',
                )
            )
        return result

    def _candidate(self, relation_detail: dict[str, Any]) -> str:
        raw = str((relation_detail or {}).get('proposed_connect_type') or '').strip()
        if not raw:
            return ''
        token = '_'.join(raw.split()).lower()
        if not token:
            return ''
        return token[:40]

    def _edge_evidence_score(self, edge) -> float:
        detail = dict(edge.relation_detail or {})
        inferred_from = str(detail.get('inferred_from') or '').strip().lower()
        claim_domain = str(detail.get('claim_domain') or '').strip().lower()
        source_type = str(detail.get('source_type') or '').strip().lower()

        source_weight = 1.0
        if inferred_from == 'search':
            source_weight = 1.15
        elif inferred_from == 'model_assertion':
            source_weight = 1.0
        elif inferred_from in {'assistant', 'user'}:
            source_weight = 0.95

        if source_type == 'search':
            source_weight += 0.05

        domain_weight = 1.0
        if claim_domain == 'world_fact':
            domain_weight = 1.05
        elif claim_domain == 'personal_memory':
            domain_weight = 0.95

        trust_factor = max(0.1, min(1.5, 0.5 + float(edge.trust_score)))
        support_factor = max(1.0, float(edge.support_count))
        return support_factor * trust_factor * source_weight * domain_weight
