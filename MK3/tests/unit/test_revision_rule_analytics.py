from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.thinking.revision_rule_analytics import aggregate_revision_rule_events, recommend_rule_adjustments


def _event(event_type: str, effect: dict):
    return SimpleNamespace(event_type=event_type, effect=effect)


def test_revision_rule_analytics_aggregates_counts_and_evidence() -> None:
    events = [
        _event(
            'edge_revision_pending',
            {
                'rule_name': 'relation_neutral',
                'marker_evidence': {'conflict_support': 1.5, 'total_evidence': 0.0},
            },
        ),
        _event(
            'edge_deactivated_for_revision',
            {
                'rule_name': 'relation_neutral',
                'marker_evidence': {'conflict_support': 2.5, 'total_evidence': 3.0},
            },
        ),
        _event(
            'edge_revision_merge_executed',
            {
                'rule_name': 'concept_neutral',
                'marker_evidence': {'conflict_support': 0.6, 'total_evidence': 4.2},
            },
        ),
    ]

    rows = aggregate_revision_rule_events(events)
    assert rows
    by_name = {row.rule_name: row for row in rows}
    assert 'relation_neutral' in by_name
    assert 'concept_neutral' in by_name

    rel = by_name['relation_neutral']
    assert rel.total_count == 2
    assert rel.pending_count == 1
    assert rel.deactivated_count == 1
    assert rel.merged_count == 0
    assert rel.conflict_evidence_sum > 3.9
    assert rel.deactivate_evidence_sum >= 3.0

    concept = by_name['concept_neutral']
    assert concept.total_count == 1
    assert concept.merged_count == 1
    assert concept.merge_evidence_sum >= 4.2


def test_revision_rule_analytics_recommends_threshold_adjustment() -> None:
    events = []
    for _ in range(9):
        events.append(
            _event(
                'edge_deactivated_for_revision',
                {
                    'rule_name': 'relation_neutral',
                    'marker_evidence': {'conflict_support': 1.2, 'total_evidence': 1.2},
                },
            )
        )
    events.append(
        _event(
            'edge_revision_pending',
            {
                'rule_name': 'relation_neutral',
                'marker_evidence': {'conflict_support': 1.0, 'total_evidence': 1.0},
            },
        )
    )

    aggregates = aggregate_revision_rule_events(events)
    suggestions = recommend_rule_adjustments(aggregates)
    assert suggestions
    assert suggestions[0].rule_name == 'relation_neutral'
    assert suggestions[0].recommendation == 'raise_deactivate_evidence_threshold'
