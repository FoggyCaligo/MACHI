from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline


def test_chat_pipeline_loads_revision_rule_overrides_into_structure_revision_service(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    override_path = tmp_path / 'revision_rule_overrides.json'
    override_payload = {
        'relation_neutral': {
            'marker_conflict_evidence_threshold_for_deactivate': 2.3,
            'marker_deactivate_support_threshold': 1,
        }
    }
    override_path.write_text(json.dumps(override_payload, ensure_ascii=False), encoding='utf-8')

    pipeline = ChatPipeline(
        db_path=db_path,
        schema_path=schema_path,
        revision_rule_overrides_path=override_path,
    )

    assert pipeline.revision_rule_overrides == override_payload
    assert pipeline.revision_rule_override_load_error == ''
    assert pipeline.thought_engine.structure_revision_service.rule_overrides == override_payload


def test_chat_pipeline_keeps_running_when_override_file_is_invalid_in_non_strict_mode(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    override_path = tmp_path / 'broken_overrides.json'
    override_path.write_text('{invalid json', encoding='utf-8')

    pipeline = ChatPipeline(
        db_path=db_path,
        schema_path=schema_path,
        revision_rule_overrides_path=override_path,
        revision_rule_overrides_strict=False,
    )

    assert pipeline.revision_rule_overrides == {}
    assert pipeline.revision_rule_override_path.endswith('broken_overrides.json')
    assert pipeline.revision_rule_override_load_error


def test_chat_pipeline_raises_in_strict_mode_when_override_file_is_invalid(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    override_path = tmp_path / 'broken_overrides.json'
    override_path.write_text('{invalid json', encoding='utf-8')

    with pytest.raises(RuntimeError):
        ChatPipeline(
            db_path=db_path,
            schema_path=schema_path,
            revision_rule_overrides_path=override_path,
            revision_rule_overrides_strict=True,
        )


def test_chat_pipeline_treats_missing_override_file_as_noop(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    missing_path = tmp_path / 'missing_overrides.json'

    pipeline = ChatPipeline(
        db_path=db_path,
        schema_path=schema_path,
        revision_rule_overrides_path=missing_path,
    )

    assert pipeline.revision_rule_overrides == {}
    assert pipeline.revision_rule_override_load_error == ''
