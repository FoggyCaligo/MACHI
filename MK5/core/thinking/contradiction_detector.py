from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import ContradictionSignal
from core.entities.thought_view import ThoughtView


@dataclass(slots=True)
class ContradictionDetector:
    medium_trust_threshold: float = 0.40
    high_trust_threshold: float = 0.25
    medium_pressure_threshold: float = 1.5
    high_pressure_threshold: float = 2.5

    def inspect(self, thought_view: ThoughtView) -> list[ContradictionSignal]:
        signals: list[ContradictionSignal] = []
        seen_edge_ids: set[int] = set()
        singular_groups: dict[tuple[int, str], list] = {}

        for edge in thought_view.edges:
            if edge.id is None or not edge.is_active:
                continue
            singular_key = self._singular_group_key(edge)
            if singular_key is not None:
                singular_groups.setdefault((edge.source_node_id, singular_key), []).append(edge)

            signal = self._inspect_one(edge)
            if signal is not None and signal.edge_id not in seen_edge_ids:
                signals.append(signal)
                seen_edge_ids.add(signal.edge_id)

        for (_source_id, _edge_type), edges in singular_groups.items():
            if len(edges) <= 1:
                continue
            ordered = sorted(edges, key=lambda item: (item.trust_score, item.edge_weight), reverse=True)
            primary = ordered[0]
            for edge in ordered[1:]:
                if edge.id is None or edge.id in seen_edge_ids:
                    continue
                score = round(max(0.6, 1.0 - edge.trust_score + edge.contradiction_pressure * 0.2), 6)
                signals.append(
                    ContradictionSignal(
                        edge_id=edge.id,
                        source_node_id=edge.source_node_id,
                        target_node_id=edge.target_node_id,
                        edge_label=edge.display_label,
                        severity='high',
                        reason=f'singular_relation_collision_with_edge_{primary.id}',
                        score=score,
                        metadata={'primary_edge_id': primary.id},
                    )
                )
                seen_edge_ids.add(edge.id)
        return signals

    def _inspect_one(self, edge) -> ContradictionSignal | None:
        severity: str | None = None
        reason: str | None = None
        score = 0.0

        if edge.revision_candidate_flag:
            severity = 'high'
            reason = 'revision_candidate_flagged'
            score = max(score, 0.9)
        if edge.conflict_count > edge.support_count and edge.conflict_count >= 2:
            severity = 'high' if edge.conflict_count - edge.support_count >= 2 else (severity or 'medium')
            reason = reason or 'conflict_outweighs_support'
            score = max(score, 0.75)
        if edge.contradiction_pressure >= self.high_pressure_threshold:
            severity = 'high'
            reason = reason or 'high_contradiction_pressure'
            score = max(score, 0.95)
        elif edge.contradiction_pressure >= self.medium_pressure_threshold:
            severity = severity or 'medium'
            reason = reason or 'medium_contradiction_pressure'
            score = max(score, 0.65)
        if edge.trust_score <= self.high_trust_threshold:
            severity = 'high'
            reason = reason or 'very_low_trust'
            score = max(score, 0.95)
        elif edge.trust_score <= self.medium_trust_threshold:
            severity = severity or 'medium'
            reason = reason or 'low_trust'
            score = max(score, 0.55)

        if severity is None or edge.id is None:
            return None
        return ContradictionSignal(
            edge_id=edge.id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            edge_label=edge.display_label,
            severity=severity,
            reason=reason or 'structural_tension',
            score=round(score, 6),
            metadata={
                'support_count': edge.support_count,
                'conflict_count': edge.conflict_count,
                'contradiction_pressure': edge.contradiction_pressure,
                'trust_score': edge.trust_score,
            },
        )

    def _singular_group_key(self, edge) -> str | None:
        semantics = edge.connect_semantics
        if edge.edge_family == 'concept' and edge.connect_type == 'neutral':
            return 'concept_identity_cluster'
        if semantics in {'same_as', 'parent_of', 'child_of', 'contradicts'}:
            return semantics
        return None
