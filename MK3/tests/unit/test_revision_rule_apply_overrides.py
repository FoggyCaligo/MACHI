from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.revision_rule_apply_overrides import _load_existing, _merge_overrides


def test_merge_overrides_overlays_generated_values_and_preserves_existing() -> None:
    existing = {
        'relation_neutral': {
            'marker_deactivate_evidence_threshold': 3.0,
            'marker_conflict_evidence_threshold_for_deactivate': 2.2,
        },
        'concept_neutral': {'marker_merge_evidence_threshold': 4.0},
    }
    generated = {
        'relation_neutral': {'marker_conflict_evidence_threshold_for_deactivate': 2.6},
        'concept_flow': {'marker_merge_evidence_threshold': 5.1},
    }
    merged = _merge_overrides(existing, generated)
    assert merged['relation_neutral']['marker_deactivate_evidence_threshold'] == 3.0
    assert merged['relation_neutral']['marker_conflict_evidence_threshold_for_deactivate'] == 2.6
    assert merged['concept_neutral']['marker_merge_evidence_threshold'] == 4.0
    assert merged['concept_flow']['marker_merge_evidence_threshold'] == 5.1


def test_load_existing_returns_empty_for_invalid_or_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / 'missing.json'
    assert _load_existing(missing) == {}

    broken = tmp_path / 'broken.json'
    broken.write_text('{broken', encoding='utf-8')
    assert _load_existing(broken) == {}

    invalid_root = tmp_path / 'invalid_root.json'
    invalid_root.write_text(json.dumps([1, 2, 3]), encoding='utf-8')
    assert _load_existing(invalid_root) == {}
