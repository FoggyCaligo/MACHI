from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RevisionRuleAggregate:
    rule_name: str
    pending_count: int = 0
    deactivated_count: int = 0
    merged_count: int = 0
    total_count: int = 0
    conflict_evidence_sum: float = 0.0
    deactivate_evidence_sum: float = 0.0
    merge_evidence_sum: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        avg_conflict = self.conflict_evidence_sum / self.total_count if self.total_count else 0.0
        avg_deactivate = self.deactivate_evidence_sum / self.total_count if self.total_count else 0.0
        avg_merge = self.merge_evidence_sum / self.total_count if self.total_count else 0.0
        return {
            'rule_name': self.rule_name,
            'total_count': self.total_count,
            'pending_count': self.pending_count,
            'deactivated_count': self.deactivated_count,
            'merged_count': self.merged_count,
            'avg_conflict_evidence': round(avg_conflict, 6),
            'avg_deactivate_evidence': round(avg_deactivate, 6),
            'avg_merge_evidence': round(avg_merge, 6),
        }


@dataclass(slots=True)
class RevisionRuleSuggestion:
    rule_name: str
    recommendation: str
    confidence: str
    rationale: str
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'rule_name': self.rule_name,
            'recommendation': self.recommendation,
            'confidence': self.confidence,
            'rationale': self.rationale,
            'metrics': dict(self.metrics),
        }


def aggregate_revision_rule_events(events: list[Any]) -> list[RevisionRuleAggregate]:
    by_rule: dict[str, RevisionRuleAggregate] = {}
    for event in events:
        event_type = str(getattr(event, 'event_type', '') or '').strip()
        if event_type not in {
            'edge_revision_pending',
            'edge_deactivated_for_revision',
            'edge_revision_merge_executed',
        }:
            continue
        effect = dict(getattr(event, 'effect', {}) or {})
        rule_name = ' '.join(str(effect.get('rule_name') or 'unknown').split()).strip() or 'unknown'
        agg = by_rule.setdefault(rule_name, RevisionRuleAggregate(rule_name=rule_name))
        agg.total_count += 1
        if event_type == 'edge_revision_pending':
            agg.pending_count += 1
        elif event_type == 'edge_deactivated_for_revision':
            agg.deactivated_count += 1
        elif event_type == 'edge_revision_merge_executed':
            agg.merged_count += 1

        evidence = dict(effect.get('marker_evidence') or {})
        agg.conflict_evidence_sum += _as_float(evidence.get('conflict_support'))
        agg.deactivate_evidence_sum += _as_float(evidence.get('total_evidence'))
        agg.merge_evidence_sum += _as_float(evidence.get('total_evidence'))

    ordered = sorted(
        by_rule.values(),
        key=lambda item: (item.total_count, item.deactivated_count, item.merged_count, item.rule_name),
        reverse=True,
    )
    return ordered


def recommend_rule_adjustments(aggregates: list[RevisionRuleAggregate]) -> list[RevisionRuleSuggestion]:
    suggestions: list[RevisionRuleSuggestion] = []
    for row in aggregates:
        if row.total_count < 5:
            continue

        deactivate_rate = row.deactivated_count / row.total_count
        pending_rate = row.pending_count / row.total_count
        merged_rate = row.merged_count / row.total_count
        avg_conflict = row.conflict_evidence_sum / row.total_count if row.total_count else 0.0
        avg_merge = row.merge_evidence_sum / row.total_count if row.total_count else 0.0

        metrics = {
            'total_count': float(row.total_count),
            'deactivate_rate': round(deactivate_rate, 6),
            'pending_rate': round(pending_rate, 6),
            'merged_rate': round(merged_rate, 6),
            'avg_conflict_evidence': round(avg_conflict, 6),
            'avg_merge_evidence': round(avg_merge, 6),
        }

        if deactivate_rate >= 0.85 and avg_conflict <= 2.0:
            suggestions.append(
                RevisionRuleSuggestion(
                    rule_name=row.rule_name,
                    recommendation='raise_deactivate_evidence_threshold',
                    confidence='medium',
                    rationale='deactivation rate is very high while conflict evidence is relatively low',
                    metrics=metrics,
                )
            )
            continue

        if pending_rate >= 0.85 and avg_conflict >= 2.8:
            suggestions.append(
                RevisionRuleSuggestion(
                    rule_name=row.rule_name,
                    recommendation='lower_deactivate_evidence_threshold',
                    confidence='medium',
                    rationale='pending dominates despite high conflict evidence',
                    metrics=metrics,
                )
            )
            continue

        if merged_rate >= 0.65 and avg_merge <= 2.2:
            suggestions.append(
                RevisionRuleSuggestion(
                    rule_name=row.rule_name,
                    recommendation='raise_merge_evidence_threshold',
                    confidence='low',
                    rationale='merge rate is high while merge evidence is relatively weak',
                    metrics=metrics,
                )
            )
            continue

        if pending_rate >= 0.70 and avg_merge >= 3.2:
            suggestions.append(
                RevisionRuleSuggestion(
                    rule_name=row.rule_name,
                    recommendation='lower_merge_evidence_threshold',
                    confidence='low',
                    rationale='merge rarely executes despite high merge evidence',
                    metrics=metrics,
                )
            )

    return suggestions


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
