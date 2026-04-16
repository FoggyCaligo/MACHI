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


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)

    return factory


def test_structure_revision_uses_revision_marker_candidates_without_flag(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='n1', address_hash='h1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='n2', address_hash='h2', raw_value='B', normalized_value='b'))
        base_edge = uow.edges.add(
            Edge(
                edge_uid='base-1',
                source_node_id=1,
                target_node_id=2,
                edge_family='concept',
                connect_type='flow',
                relation_detail={'kind': 'name_variant'},
                trust_score=0.65,
                support_count=2,
                contradiction_pressure=0.1,
            )
        )
        RevisionEdgeService().record_conflict_assertion(
            uow,
            base_edge=base_edge,
            reason='conflict_connect_type',
            signal_score=0.62,
            message_id=10,
        )
        uow.commit()

    with uow_factory() as uow:
        actions = StructureRevisionService().review_candidates(uow, message_id=11, limit=20)
        uow.commit()
        assert actions
        assert any(action.edge_id == (base_edge.id or 0) for action in actions)
        assert any(action.action == 'revision_pending' for action in actions)


def test_structure_revision_deactivates_when_deactivate_marker_support_accumulates(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='n1', address_hash='h1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='n2', address_hash='h2', raw_value='B', normalized_value='b'))
        base_edge = uow.edges.add(
            Edge(
                edge_uid='base-2',
                source_node_id=1,
                target_node_id=2,
                edge_family='relation',
                connect_type='neutral',
                relation_detail={'kind': 'co_occurs_with'},
                trust_score=0.9,
                support_count=3,
                contradiction_pressure=0.1,
                conflict_count=0,
            )
        )
        service = RevisionEdgeService()
        service.record_revision_marker(
            uow,
            base_edge=base_edge,
            kind='deactivate_candidate',
            reason='manual_deactivate_vote',
            message_id=None,
            status='open',
        )
        service.record_revision_marker(
            uow,
            base_edge=base_edge,
            kind='deactivate_candidate',
            reason='manual_deactivate_vote',
            message_id=None,
            status='open',
        )
        uow.commit()

    with uow_factory() as uow:
        actions = StructureRevisionService().review_candidates(uow, message_id=None, limit=20)
        uow.commit()
        assert any(action.edge_id == (base_edge.id or 0) and action.action == 'edge_deactivated' for action in actions)
        updated = uow.edges.get_by_id(base_edge.id or 0)
        assert updated is not None
        assert updated.is_active is False
