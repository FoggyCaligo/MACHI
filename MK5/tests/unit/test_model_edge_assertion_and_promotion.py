from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.thought_view import ThoughtView
from core.thinking.contradiction_detector import ContradictionDetector
from core.thinking.structure_revision_service import StructureRevisionService
from core.update.connect_type_promotion_service import ConnectTypePromotionService
from core.update.model_edge_assertion_service import ModelEdgeAssertionService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)
    return factory


class FakeClient:
    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, **kwargs):  # noqa: ANN003
        return SimpleNamespace(content=self._content)


def _seed_two_nodes(uow_factory) -> None:  # noqa: ANN001
    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='n1', address_hash='h1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='n2', address_hash='h2', raw_value='B', normalized_value='b'))
        uow.commit()


def test_model_edge_assertion_keeps_unknown_connect_type_as_proposal(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)
    _seed_two_nodes(uow_factory)

    service = ModelEdgeAssertionService(
        uow_factory=uow_factory,
        client=FakeClient(
            '{"new_edges":[{"from_node_id":1,"to_node_id":2,"edge_family":"concept","connect_type":"reflective","relation_detail":{"kind":"name_variant"}}]}'
        ),
    )
    thought_view = ThoughtView(
        session_id='s',
        message_text='A is also called B',
        nodes=[
            Node(id=1, node_uid='n1', address_hash='h1', raw_value='A', normalized_value='a'),
            Node(id=2, node_uid='n2', address_hash='h2', raw_value='B', normalized_value='b'),
        ],
    )

    result = service.assert_edges(model_name='gemma3:4b', message='A is also called B', thought_view=thought_view)
    assert result.attempted is True
    assert result.created_edge_ids

    with uow_factory() as uow:
        edge = uow.edges.get_by_id(result.created_edge_ids[0])
        assert edge is not None
        assert edge.connect_type == 'neutral'
        assert edge.relation_detail.get('proposed_connect_type') == 'reflective'


def test_connect_type_promotion_promotes_repeated_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)
    with uow_factory() as uow:
        for idx in range(1, 5):
            uow.nodes.add(
                Node(node_uid=f'n{idx}', address_hash=f'h{idx}', raw_value=f'N{idx}', normalized_value=f'n{idx}')
            )
        uow.edges.add(
            Edge(
                edge_uid='e12',
                source_node_id=1,
                target_node_id=2,
                edge_family='concept',
                connect_type='neutral',
                relation_detail={'kind': 'name_variant', 'proposed_connect_type': 'reflective'},
                support_count=1,
                trust_score=0.6,
            )
        )
        uow.edges.add(
            Edge(
                edge_uid='e23',
                source_node_id=2,
                target_node_id=3,
                edge_family='concept',
                connect_type='neutral',
                relation_detail={'kind': 'name_variant', 'proposed_connect_type': 'reflective'},
                support_count=1,
                trust_score=0.6,
            )
        )
        uow.edges.add(
            Edge(
                edge_uid='e34',
                source_node_id=3,
                target_node_id=4,
                edge_family='concept',
                connect_type='neutral',
                relation_detail={'kind': 'name_variant', 'proposed_connect_type': 'reflective'},
                support_count=1,
                trust_score=0.6,
            )
        )
        uow.commit()

    service = ConnectTypePromotionService(threshold=3, max_scan=50)
    with uow_factory() as uow:
        result = service.promote(uow, message_id=None)
        uow.commit()
        assert result.attempted is True
        assert result.promotions
        promoted = result.promotions[0]
        assert promoted.proposed_connect_type == 'reflective'
        assert len(promoted.promoted_edge_ids) >= 1

    with uow_factory() as uow:
        out = uow.edges.list_outgoing(1, active_only=True)
        assert any(edge.connect_type == 'reflective' for edge in out)


def test_connect_type_promotion_respects_trust_and_source_weight(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)
    with uow_factory() as uow:
        for idx in range(1, 5):
            uow.nodes.add(
                Node(node_uid=f'n{idx}', address_hash=f'h{idx}', raw_value=f'N{idx}', normalized_value=f'n{idx}')
            )
        # Low trust and no strong source hint: should not pass threshold=5.
        uow.edges.add(
            Edge(
                edge_uid='weak-1',
                source_node_id=1,
                target_node_id=2,
                edge_family='concept',
                connect_type='neutral',
                relation_detail={'kind': 'name_variant', 'proposed_connect_type': 'reflective', 'inferred_from': 'assistant'},
                support_count=2,
                trust_score=0.20,
            )
        )
        uow.edges.add(
            Edge(
                edge_uid='weak-2',
                source_node_id=2,
                target_node_id=3,
                edge_family='concept',
                connect_type='neutral',
                relation_detail={'kind': 'name_variant', 'proposed_connect_type': 'reflective', 'inferred_from': 'assistant'},
                support_count=2,
                trust_score=0.20,
            )
        )
        uow.commit()

    strict_service = ConnectTypePromotionService(threshold=5, max_scan=50)
    with uow_factory() as uow:
        weak_result = strict_service.promote(uow, message_id=None)
        uow.commit()
        assert weak_result.attempted is True
        assert len(weak_result.promotions) == 0

    with uow_factory() as uow:
        # Add one strong search-grounded edge; weighted evidence should pass threshold now.
        uow.edges.add(
            Edge(
                edge_uid='strong-1',
                source_node_id=3,
                target_node_id=4,
                edge_family='concept',
                connect_type='neutral',
                relation_detail={
                    'kind': 'name_variant',
                    'proposed_connect_type': 'reflective',
                    'inferred_from': 'search',
                    'source_type': 'search',
                    'claim_domain': 'world_fact',
                },
                support_count=3,
                trust_score=0.90,
            )
        )
        uow.commit()

    with uow_factory() as uow:
        strong_result = strict_service.promote(uow, message_id=None)
        uow.commit()
        assert len(strong_result.promotions) >= 1

def test_hierarchical_concept_flow_is_not_merged_during_revision(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)
    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='n1', address_hash='h1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='n2', address_hash='h2', raw_value='B', normalized_value='b'))
        edge = uow.edges.add(
            Edge(
                edge_uid='opp-1',
                source_node_id=1,
                target_node_id=2,
                edge_family='concept',
                connect_type='flow',
                relation_detail={'kind': 'subtype_of'},
                trust_score=0.39,
                support_count=1,
                conflict_count=1,
                contradiction_pressure=1.7,
                revision_candidate_flag=True,
            )
        )
        uow.commit()

    view = ThoughtView(
        session_id='s',
        message_text='A is a subtype of B',
        edges=[edge],
    )
    signals = ContradictionDetector().inspect(view)
    assert signals

    service = StructureRevisionService()
    with uow_factory() as uow:
        actions = service.review_candidates(uow, message_id=1, limit=10)
        uow.commit()
        assert all(action.action != 'node_merged' for action in actions)

    with uow_factory() as uow:
        kept = uow.edges.get_by_id(edge.id)
        assert kept is not None
        assert kept.is_active is True
        assert kept.connect_type == 'flow'


def test_opposite_connect_type_emits_dedicated_contradiction_reason() -> None:
    edge = Edge(
        id=77,
        edge_uid='opp',
        source_node_id=1,
        target_node_id=2,
        edge_family='concept',
        connect_type='opposite',
        relation_detail={'kind': 'opposes'},
        support_count=1,
        conflict_count=0,
        contradiction_pressure=0.0,
        trust_score=0.8,
        is_active=True,
    )
    view = ThoughtView(session_id='s', message_text='A opposes B', edges=[edge])
    signals = ContradictionDetector().inspect(view)
    assert signals
    assert signals[0].reason == 'opposite_connect_type'
