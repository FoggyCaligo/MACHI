from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.thinking.revision_rule_tuner import build_rule_overrides_from_suggestions


def test_revision_rule_tuner_builds_overrides_with_preset() -> None:
    suggestions = [
        {
            'rule_name': 'relation_neutral',
            'recommendation': 'raise_deactivate_evidence_threshold',
            'confidence': 'medium',
            'rationale': 'fixture',
        },
        {
            'rule_name': 'concept_neutral',
            'recommendation': 'lower_merge_evidence_threshold',
            'confidence': 'low',
            'rationale': 'fixture',
        },
    ]
    overrides = build_rule_overrides_from_suggestions(suggestions, preset='balanced')
    assert 'relation_neutral' in overrides
    assert 'concept_neutral' in overrides
    assert overrides['relation_neutral']['marker_conflict_evidence_threshold_for_deactivate'] > 0
    assert overrides['concept_neutral']['marker_merge_evidence_threshold'] >= 0.05


def test_revision_rule_tuner_aggressive_has_smaller_delta_than_conservative() -> None:
    suggestions = [
        {'rule_name': 'relation_neutral', 'recommendation': 'raise_deactivate_evidence_threshold'}
    ]
    aggressive = build_rule_overrides_from_suggestions(suggestions, preset='aggressive')
    conservative = build_rule_overrides_from_suggestions(suggestions, preset='conservative')
    a = aggressive['relation_neutral']['marker_conflict_evidence_threshold_for_deactivate']
    c = conservative['relation_neutral']['marker_conflict_evidence_threshold_for_deactivate']
    assert c > a
