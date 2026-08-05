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
from core.entities.node_pointer import NodePointer
from core.update.node_merge_service import NodeMergeRequest, NodeMergeService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'memory.db'
        schema_path = ROOT / 'storage' / 'schema.sql'

        def make_uow() -> SqliteUnitOfWork:
            return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)

        with make_uow() as uow:
            event = uow.graph_events.add(
                GraphEvent(
                    event_uid='evt-root',
                    event_type='fixture_created',
                    input_text='fixture',
                )
            )
            canonical = uow.nodes.add(
                Node(
                    node_uid='node-canonical',
                    address_hash='hash-canonical',
                    node_kind='noun_phrase',
                    raw_value='십자가',
                    normalized_value='십자가',
                    payload={'source_counts': {'user': 2}, 'label': 'canonical'},
                    trust_score=0.7,
                    stability_score=0.6,
                    created_from_event_id=event.id,
                )
            )
            absorbed = uow.nodes.add(
                Node(
                    node_uid='node-absorbed',
                    address_hash='hash-absorbed',
                    node_kind='noun_phrase',
                    raw_value='cross',
                    normalized_value='cross',
                    payload={'source_counts': {'search': 1}, 'label': 'absorbed'},
                    trust_score=0.9,
                    stability_score=0.8,
                    created_from_event_id=event.id,
                )
            )
            target = uow.nodes.add(
                Node(
                    node_uid='node-target',
                    address_hash='hash-target',
                    node_kind='noun_phrase',
                    raw_value='도형',
                    normalized_value='도형',
                    payload={},
                    created_from_event_id=event.id,
                )
            )
            owner = uow.nodes.add(
                Node(
                    node_uid='node-owner',
                    address_hash='hash-owner',
                    node_kind='noun_phrase',
                    raw_value='기하',
                    normalized_value='기하',
                    payload={},
                    created_from_event_id=event.id,
                )
            )

            kept_edge = uow.edges.add(
                Edge(
                    edge_uid='edge-kept',
                    source_node_id=canonical.id or 0,
                    target_node_id=target.id or 0,
                    edge_family='relation',
                    connect_type='neutral',
                    relation_detail={'source_counts': {'user': 1}, 'note': 'same sentence user'},
                    edge_weight=0.2,
                    trust_score=0.5,
                    support_count=2,
                    created_from_event_id=event.id,
                )
            )
            merged_edge = uow.edges.add(
                Edge(
                    edge_uid='edge-merged',
                    source_node_id=absorbed.id or 0,
                    target_node_id=target.id or 0,
                    edge_family='relation',
                    connect_type='neutral',
                    relation_detail={'source_counts': {'search': 1}, 'note': 'same sentence search'},
                    edge_weight=0.4,
                    trust_score=0.8,
                    support_count=3,
                    created_from_event_id=event.id,
                )
            )
            rewired_edge = uow.edges.add(
                Edge(
                    edge_uid='edge-rewired',
                    source_node_id=owner.id or 0,
                    target_node_id=absorbed.id or 0,
                    edge_family='relation',
                    connect_type='flow',
                    relation_detail={'reason': 'fixture', 'note': 'fixture support relation'},
                    edge_weight=0.3,
                    trust_score=0.6,
                    support_count=1,
                    created_from_event_id=event.id,
                )
            )
            kept_pointer = uow.node_pointers.add(
                NodePointer(
                    pointer_uid='ptr-kept',
                    owner_node_id=canonical.id or 0,
                    referenced_node_id=target.id or 0,
                    pointer_type='partial_reuse',
                    pointer_slot='contained_block',
                    detail={'source': 'canonical'},
                    created_from_event_id=event.id,
                )
            )
            merged_pointer = uow.node_pointers.add(
                NodePointer(
                    pointer_uid='ptr-merged',
                    owner_node_id=absorbed.id or 0,
                    referenced_node_id=target.id or 0,
                    pointer_type='partial_reuse',
                    pointer_slot='contained_block',
                    detail={'source': 'absorbed'},
                    created_from_event_id=event.id,
                )
            )
            rewired_pointer = uow.node_pointers.add(
                NodePointer(
                    pointer_uid='ptr-rewired',
                    owner_node_id=owner.id or 0,
                    referenced_node_id=absorbed.id or 0,
                    pointer_type='reference',
                    pointer_slot=None,
                    detail={'source': 'owner'},
                    created_from_event_id=event.id,
                )
            )
            assert kept_edge.id and merged_edge.id and rewired_edge.id
            assert kept_pointer.id and merged_pointer.id and rewired_pointer.id

        service = NodeMergeService(make_uow)
        result = service.merge(
            NodeMergeRequest(
                canonical_node_id=canonical.id or 0,
                absorbed_node_ids=[absorbed.id or 0],
                merge_reason='test_merge',
            )
        )

        assert result.canonical_node_id == (canonical.id or 0)
        assert result.absorbed_node_ids == [absorbed.id or 0]
        assert merged_edge.id in result.merged_edge_ids
        assert rewired_edge.id in result.rewired_edge_ids
        assert merged_pointer.id in result.merged_pointer_ids
        assert rewired_pointer.id in result.rewired_pointer_ids
        assert absorbed.id in result.deactivated_node_ids
        assert result.created_event_ids

        with make_uow() as uow:
            canonical_after = uow.nodes.get_by_id(canonical.id or 0)
            absorbed_after = uow.nodes.get_by_id(absorbed.id or 0)
            assert canonical_after is not None
            assert absorbed_after is not None and not absorbed_after.is_active
            assert absorbed_after.revision_state == 'merged'
            assert canonical_after.trust_score == 0.9
            assert canonical_after.stability_score == 0.8
            assert canonical_after.payload['source_counts'] == {'user': 2, 'search': 1}
            assert canonical_after.payload['merged_from'][0]['node_id'] == (absorbed.id or 0)

            surviving_edge = uow.edges.find_active_relation(
                canonical.id or 0,
                target.id or 0,
                edge_family='relation',
                connect_type='neutral',
            )
            assert surviving_edge is not None
            assert surviving_edge.support_count == 5
            assert surviving_edge.trust_score == 0.8
            assert surviving_edge.edge_weight == 0.4
            assert surviving_edge.relation_detail['source_counts'] == {'user': 1, 'search': 1}
            assert (merged_edge.id or 0) in surviving_edge.relation_detail['merged_edge_ids']

            moved_edge = uow.edges.find_active_relation(
                owner.id or 0,
                canonical.id or 0,
                edge_family='relation',
                connect_type='flow',
            )
            assert moved_edge is not None and moved_edge.id == rewired_edge.id
            assert moved_edge.relation_detail['rewrite_history'][0]['from_node_id'] == (absorbed.id or 0)

            surviving_pointer = uow.node_pointers.find_active(
                canonical.id or 0,
                target.id or 0,
                'partial_reuse',
                pointer_slot='contained_block',
            )
            assert surviving_pointer is not None
            assert (merged_pointer.id or 0) in surviving_pointer.detail['merged_pointer_ids']

            moved_pointer = uow.node_pointers.find_active(owner.id or 0, canonical.id or 0, 'reference')
            assert moved_pointer is not None and moved_pointer.id == rewired_pointer.id
            assert moved_pointer.detail['rewrite_history'][0]['to_node_id'] == (canonical.id or 0)


if __name__ == '__main__':
    main()
