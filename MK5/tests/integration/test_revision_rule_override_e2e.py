from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.edge import Edge
from core.entities.node import Node
from core.thinking.structure_revision_service import StructureRevisionService
from core.update.revision_edge_service import RevisionEdgeService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def _build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)

    return factory


def _run_revision_once(
    base_dir: Path,
    *,
    suffix: str,
    rule_overrides: dict[str, dict[str, object]] | None = None,
) -> str:
    db_path = base_dir / f'memory_{suffix}.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = _build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='n1', address_hash='h1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='n2', address_hash='h2', raw_value='B', normalized_value='b'))
        base_edge = uow.edges.add(
            Edge(
                edge_uid='base-rule-override-e2e',
                source_node_id=1,
                target_node_id=2,
                edge_family='relation',
                connect_type='neutral',
                relation_detail={'kind': 'co_occurs_with'},
                trust_score=0.9,
                support_count=1,
                conflict_count=0,
                contradiction_pressure=0.0,
            )
        )
        RevisionEdgeService().record_conflict_assertion(
            uow,
            base_edge=base_edge,
            reason='override_e2e_fixture',
            signal_score=0.95,
            message_id=1,
        )
        uow.commit()

    service = StructureRevisionService(rule_overrides=rule_overrides)
    with uow_factory() as uow:
        actions = service.review_candidates(uow, message_id=None, limit=20)
        uow.commit()
        target = [item for item in actions if item.edge_id == 1]
        assert target
        return target[0].action


def test_revision_rule_override_changes_execution_outcome_e2e(tmp_path: Path) -> None:
    default_action = _run_revision_once(tmp_path, suffix='default', rule_overrides=None)
    overridden_action = _run_revision_once(
        tmp_path,
        suffix='override',
        rule_overrides={
            'relation_neutral': {
                'marker_conflict_support_threshold_for_deactivate': 99,
                'marker_conflict_evidence_threshold_for_deactivate': 2.0,
            }
        }
    )

    assert default_action == 'revision_pending'
    assert overridden_action == 'edge_deactivated'
