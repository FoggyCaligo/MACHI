from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.edge import Edge
from core.entities.node import Node
from core.update.revision_edge_service import (
    REVISION_KIND_PENDING,
    RevisionEdgeService,
)
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)

    return factory


def test_revision_marker_upserts_with_standard_detail(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='n1', address_hash='h1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='n2', address_hash='h2', raw_value='B', normalized_value='b'))
        base = uow.edges.add(
            Edge(
                edge_uid='base',
                source_node_id=1,
                target_node_id=2,
                edge_family='concept',
                connect_type='flow',
                relation_detail={'kind': 'subtype_of'},
                support_count=1,
                trust_score=0.7,
            )
        )
        uow.commit()

    service = RevisionEdgeService()
    with uow_factory() as uow:
        created = service.record_revision_marker(
            uow,
            base_edge=base,
            kind=REVISION_KIND_PENDING,
            reason='candidate_but_not_below_floor',
            message_id=11,
            status='open',
            metadata={'trust_score': 0.7},
        )
        supported = service.record_revision_marker(
            uow,
            base_edge=base,
            kind=REVISION_KIND_PENDING,
            reason='candidate_but_not_below_floor',
            message_id=12,
            status='open',
            metadata={'trust_score': 0.69},
        )
        uow.commit()

        assert created.action == 'created'
        assert supported.action == 'supported'
        marker = uow.edges.get_by_id(created.edge_id or 0)
        assert marker is not None
        assert marker.connect_type == 'neutral'
        assert marker.support_count >= 2
        assert marker.relation_detail.get('purpose') == 'revision'
        assert marker.relation_detail.get('kind') == REVISION_KIND_PENDING
        assert marker.relation_detail.get('status') == 'open'
        assert marker.relation_detail.get('source_edge_ids') == [base.id]
