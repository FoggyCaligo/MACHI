from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.edge import Edge
from core.entities.node import Node
from core.update.temporary_edge_service import TemporaryEdgeService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)

    return factory


def _anchor_address(session_id: str, anchor_key: str) -> str:
    import hashlib

    payload = f'identity_anchor::{session_id}::{anchor_key}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]


def test_temporary_edge_cleanup_triggers_on_shifted_topic(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)
    session_id = 'session-temp-1'

    with uow_factory() as uow:
        anchor = uow.nodes.add(
            Node(
                node_uid='anchor-user',
                address_hash=_anchor_address(session_id, 'participant_user'),
                raw_value='participant_user',
                normalized_value='participant_user',
            )
        )
        target = uow.nodes.add(Node(node_uid='topic-a', address_hash='h-topic-a', raw_value='갑옷', normalized_value='갑옷'))
        temp_edge = uow.edges.add(
            Edge(
                edge_uid='temp-edge-1',
                source_node_id=anchor.id or 0,
                target_node_id=target.id or 0,
                edge_family='relation',
                connect_type='flow',
                relation_detail={
                    'scope': 'session_temporary',
                    'temporary_edge': True,
                    'session_id': session_id,
                },
                is_active=True,
            )
        )
        durable_edge = uow.edges.add(
            Edge(
                edge_uid='durable-edge-1',
                source_node_id=anchor.id or 0,
                target_node_id=target.id or 0,
                edge_family='relation',
                connect_type='neutral',
                relation_detail={'scope': 'sentence'},
                is_active=True,
            )
        )
        uow.commit()

    service = TemporaryEdgeService()
    result = service.cleanup_on_topic_shift(
        uow_factory,
        session_id=session_id,
        current_turn_index=7,
        intent_snapshot={'shifted': True, 'topic_continuity': 'shifted_topic', 'topic_overlap_count': 0},
    )
    assert result.triggered is True
    assert (temp_edge.id or 0) in result.deactivated_edge_ids
    assert (durable_edge.id or 0) not in result.deactivated_edge_ids

    with uow_factory() as uow:
        temp_after = uow.edges.get_by_id(temp_edge.id or 0)
        durable_after = uow.edges.get_by_id(durable_edge.id or 0)
        assert temp_after is not None and temp_after.is_active is False
        assert durable_after is not None and durable_after.is_active is True


def test_temporary_edge_cleanup_skips_when_topic_not_shifted(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)
    session_id = 'session-temp-2'

    with uow_factory() as uow:
        anchor = uow.nodes.add(
            Node(
                node_uid='anchor-user-2',
                address_hash=_anchor_address(session_id, 'participant_user'),
                raw_value='participant_user',
                normalized_value='participant_user',
            )
        )
        target = uow.nodes.add(Node(node_uid='topic-b', address_hash='h-topic-b', raw_value='가죽갑옷', normalized_value='가죽갑옷'))
        temp_edge = uow.edges.add(
            Edge(
                edge_uid='temp-edge-2',
                source_node_id=anchor.id or 0,
                target_node_id=target.id or 0,
                edge_family='relation',
                connect_type='flow',
                relation_detail={
                    'scope': 'session_temporary',
                    'temporary_edge': True,
                    'session_id': session_id,
                },
                is_active=True,
            )
        )
        uow.commit()

    service = TemporaryEdgeService()
    result = service.cleanup_on_topic_shift(
        uow_factory,
        session_id=session_id,
        current_turn_index=3,
        intent_snapshot={'shifted': False, 'topic_continuity': 'related_topic', 'topic_overlap_count': 1},
    )
    assert result.triggered is False
    assert result.deactivated_edge_ids == []

    with uow_factory() as uow:
        temp_after = uow.edges.get_by_id(temp_edge.id or 0)
        assert temp_after is not None and temp_after.is_active is True

