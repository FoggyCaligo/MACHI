from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.conclusion import ContradictionSignal
from core.entities.edge import Edge
from core.entities.node import Node
from core.thinking.trust_manager import TrustManager
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)
    return factory


def test_trust_manager_creates_and_supports_conflict_edge(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = Path(__file__).resolve().parents[2] / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='node-11', address_hash='hash-11', raw_value='n11', normalized_value='n11'))
        uow.nodes.add(Node(node_uid='node-22', address_hash='hash-22', raw_value='n22', normalized_value='n22'))
        edge = uow.edges.add(
            Edge(
                edge_uid='edge-main',
                source_node_id=1,
                target_node_id=2,
                edge_family='relation',
                connect_type='flow',
                relation_detail={'note': 'main edge'},
                trust_score=0.8,
                support_count=3,
            )
        )
        uow.commit()

    signal = ContradictionSignal(
        edge_id=edge.id or 0,
        source_node_id=1,
        target_node_id=2,
        edge_label='relation/flow',
        severity='medium',
        reason='conflict_outweighs_support',
        score=0.7,
    )

    manager = TrustManager()
    with uow_factory() as uow:
        manager.apply_signal(uow, signal, message_id=None)
        manager.apply_signal(uow, signal, message_id=None)
        conflict_edge = uow.edges.find_active_relation(1, 2, edge_family='relation', connect_type='conflict')
        assert conflict_edge is not None
        assert conflict_edge.support_count == 2
        assert conflict_edge.trust_score > 0.35
        assert conflict_edge.relation_detail['purpose'] == 'revision'
        assert conflict_edge.connect_type == 'conflict'
        assert conflict_edge.relation_detail['source_edge_ids'] == [edge.id]
        assert 'conflict_outweighs_support' in conflict_edge.relation_detail['reasons']
        recent_types = {event.event_type for event in uow.graph_events.list_recent(limit=20)}
        assert 'conflict_edge_created' in recent_types
        assert 'conflict_edge_supported' in recent_types
