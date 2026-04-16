from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from core.thinking.structure_revision_service import StructureRevisionService
from core.update.node_merge_service import NodeMergeService
from core.update.revision_edge_service import RevisionEdgeService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)
    return factory


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'memory.db'
        schema_path = ROOT / 'storage' / 'schema.sql'
        uow_factory = build_uow_factory(db_path, schema_path)

        with uow_factory() as uow:
            event = uow.graph_events.add(
                GraphEvent(event_uid='evt-root', event_type='fixture_created', input_text='fixture')
            )
            node_a = uow.nodes.add(
                Node(
                    node_uid='node-a',
                    address_hash='addr-a',
                    node_kind='noun_phrase',
                    raw_value='MK5',
                    normalized_value='mk5',
                    payload={'source_counts': {'user': 2}, 'raw_aliases': ['mk5']},
                    trust_score=0.82,
                    stability_score=0.77,
                    created_from_event_id=event.id,
                )
            )
            node_b = uow.nodes.add(
                Node(
                    node_uid='node-b',
                    address_hash='addr-b',
                    node_kind='noun_phrase',
                    raw_value='mk5',
                    normalized_value='mk5',
                    payload={'source_counts': {'search': 1}},
                    trust_score=0.65,
                    stability_score=0.52,
                    created_from_event_id=event.id,
                )
            )
            target = uow.nodes.add(
                Node(
                    node_uid='node-target',
                    address_hash='addr-target',
                    node_kind='noun_phrase',
                    raw_value='graph',
                    normalized_value='graph',
                    payload={},
                    created_from_event_id=event.id,
                )
            )
            edge = uow.edges.add(
                Edge(
                    edge_uid='edge-revision',
                    source_node_id=node_a.id or 0,
                    target_node_id=node_b.id or 0,
                    edge_family='concept',
                    connect_type='opposite',
                    relation_detail={'fixture': True, 'note': 'opposite fixture'},
                    edge_weight=0.2,
                    trust_score=0.39,
                    support_count=1,
                    conflict_count=2,
                    contradiction_pressure=2.2,
                    revision_candidate_flag=True,
                    created_from_event_id=event.id,
                )
            )
            carried = uow.edges.add(
                Edge(
                    edge_uid='edge-carried',
                    source_node_id=node_b.id or 0,
                    target_node_id=target.id or 0,
                    edge_family='relation',
                    connect_type='flow',
                    relation_detail={'fixture': 'carried', 'note': 'carried relation'},
                    edge_weight=0.6,
                    trust_score=0.7,
                    support_count=1,
                    created_from_event_id=event.id,
                )
            )
            uow.commit()

        with uow_factory() as uow:
            edge_for_marker = uow.edges.get_by_id(edge.id or 0)
            assert edge_for_marker is not None
            RevisionEdgeService().record_conflict_assertion(
                uow,
                base_edge=edge_for_marker,
                reason='conflict_outweighs_support',
                signal_score=0.8,
                message_id=None,
            )
            uow.commit()

        service = StructureRevisionService(node_merge_service=NodeMergeService(uow_factory))
        with uow_factory() as uow:
            actions = service.review_candidates(uow, message_id=None)
            uow.commit()

        assert actions, 'revision review should emit at least one action'
        merge_actions = [item for item in actions if item.action == 'node_merged']
        assert merge_actions, 'duplicate-like revision candidate should trigger node merge'
        metadata = merge_actions[0].metadata
        assert metadata['canonical_node_id'] == (node_a.id or 0)
        assert metadata['absorbed_node_id'] == (node_b.id or 0)

        with uow_factory() as uow:
            node_a_after = uow.nodes.get_by_id(node_a.id or 0)
            node_b_after = uow.nodes.get_by_id(node_b.id or 0)
            assert node_a_after is not None and node_a_after.is_active
            assert node_b_after is not None and not node_b_after.is_active
            moved = uow.edges.find_active_relation(
                node_a.id or 0,
                target.id or 0,
                edge_family='relation',
                connect_type='flow',
            )
            assert moved is not None and moved.id == (carried.id or 0)
            event_types = {event.event_type for event in uow.graph_events.list_recent(limit=20)}
            assert 'node_merged' in event_types

        print('PASS: revision-driven node merge')


if __name__ == '__main__':
    main()
