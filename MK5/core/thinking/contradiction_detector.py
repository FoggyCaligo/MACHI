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
        for edge in thought_view.edges:
            if edge.id is None or not edge.is_active:
                continue
            signal = self._inspect_one(edge)
            if signal is not None and signal.edge_id not in seen_edge_ids:
                signals.append(signal)
                seen_edge_ids.add(signal.edge_id)

        return signals

    def _inspect_one(self, edge) -> ContradictionSignal | None:
        severity: str | None = None
        reason: str | None = None
        score = 0.0
        medium_pressure_threshold = self.medium_pressure_threshold
        high_pressure_threshold = self.high_pressure_threshold

        if edge.is_conflict:
            medium_pressure_threshold = max(1.0, self.medium_pressure_threshold - 0.5)
            high_pressure_threshold = max(2.0, self.high_pressure_threshold - 0.5)
            if edge.support_count > 0 or edge.conflict_count > 0 or edge.contradiction_pressure > 0:
                severity = 'medium'
                reason = 'conflict_connect_type'
                score = max(score, 0.45)
        elif edge.connect_type == 'opposite':
            medium_pressure_threshold = max(1.2, self.medium_pressure_threshold - 0.3)
            high_pressure_threshold = max(2.2, self.high_pressure_threshold - 0.3)
            if edge.support_count > 0 or edge.conflict_count > 0 or edge.contradiction_pressure > 0:
                severity = 'medium'
                reason = 'opposite_connect_type'
                score = max(score, 0.4)

        if edge.conflict_count > edge.support_count and edge.conflict_count >= 2:
            severity = 'high' if edge.conflict_count - edge.support_count >= 2 else (severity or 'medium')
            reason = reason or 'conflict_outweighs_support'
            score = max(score, 0.75)
        if edge.contradiction_pressure >= high_pressure_threshold:
            severity = 'high'
            reason = reason or 'high_contradiction_pressure'
            score = max(score, 0.95)
        elif edge.contradiction_pressure >= medium_pressure_threshold:
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
