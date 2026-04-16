from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.edge import Edge
from core.entities.node import Node
from core.thinking.structure_revision_service import RevisionExecutionRule, StructureRevisionService
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
                relation_detail={},
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
        actions = StructureRevisionService().review_candidates(uow, message_id=None, limit=20)
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
                relation_detail={},
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
            marker_role='deactivate_candidate',
            reason='manual_deactivate_vote',
            message_id=None,
            status='open',
        )
        service.record_revision_marker(
            uow,
            base_edge=base_edge,
            marker_role='deactivate_candidate',
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


def test_structure_revision_uses_execution_rule_table_for_thresholds(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='n10', address_hash='h10', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='n20', address_hash='h20', raw_value='B', normalized_value='b'))
        base_edge = uow.edges.add(
            Edge(
                edge_uid='base-rule-1',
                source_node_id=1,
                target_node_id=2,
                edge_family='relation',
                connect_type='neutral',
                relation_detail={},
                trust_score=0.9,
                support_count=2,
                contradiction_pressure=0.0,
                conflict_count=0,
            )
        )
        RevisionEdgeService().record_revision_marker(
            uow,
            base_edge=base_edge,
            marker_role='deactivate_candidate',
            reason='single_vote',
            message_id=None,
            status='open',
        )
        uow.commit()

    custom_rules = (
        RevisionExecutionRule(
            name='relation-neutral-fast-deactivate',
            edge_families=('relation',),
            connect_types=('neutral',),
            marker_deactivate_support_threshold=1,
        ),
        RevisionExecutionRule(name='fallback'),
    )
    service = StructureRevisionService(execution_rules=custom_rules)

    with uow_factory() as uow:
        actions = service.review_candidates(uow, message_id=None, limit=20)
        uow.commit()
        assert any(action.edge_id == (base_edge.id or 0) and action.action == 'edge_deactivated' for action in actions)


def test_structure_revision_default_rules_branch_by_family_and_connect_type(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='a1', address_hash='ha1', raw_value='A1', normalized_value='a1'))
        uow.nodes.add(Node(node_uid='a2', address_hash='ha2', raw_value='A2', normalized_value='a2'))
        uow.nodes.add(Node(node_uid='b1', address_hash='hb1', raw_value='B1', normalized_value='b1'))
        uow.nodes.add(Node(node_uid='b2', address_hash='hb2', raw_value='B2', normalized_value='b2'))

        concept_conflict = uow.edges.add(
            Edge(
                edge_uid='edge-concept-conflict',
                source_node_id=1,
                target_node_id=2,
                edge_family='concept',
                connect_type='conflict',
                relation_detail={},
                trust_score=0.30,
                support_count=1,
                conflict_count=1,
                contradiction_pressure=1.0,
            )
        )
        relation_neutral = uow.edges.add(
            Edge(
                edge_uid='edge-relation-neutral',
                source_node_id=3,
                target_node_id=4,
                edge_family='relation',
                connect_type='neutral',
                relation_detail={},
                trust_score=0.30,
                support_count=1,
                conflict_count=1,
                contradiction_pressure=1.0,
            )
        )

        marker_service = RevisionEdgeService()
        marker_service.record_conflict_assertion(
            uow,
            base_edge=concept_conflict,
            reason='rule-branch-check',
            signal_score=0.6,
            message_id=None,
        )
        marker_service.record_conflict_assertion(
            uow,
            base_edge=relation_neutral,
            reason='rule-branch-check',
            signal_score=0.6,
            message_id=None,
        )
        uow.commit()

    with uow_factory() as uow:
        actions = StructureRevisionService().review_candidates(uow, message_id=None, limit=20)
        uow.commit()
        by_edge = {action.edge_id: action for action in actions}
        concept_action = by_edge.get(concept_conflict.id or 0)
        relation_action = by_edge.get(relation_neutral.id or 0)
        assert concept_action is not None
        assert relation_action is not None
        assert concept_action.action == 'edge_deactivated'
        assert relation_action.action == 'revision_pending'
        assert (concept_action.metadata or {}).get('rule_name') == 'concept_conflict'
        assert (relation_action.metadata or {}).get('rule_name') == 'relation_neutral'


def test_structure_revision_uses_marker_evidence_threshold_when_support_count_is_low(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='ev1', address_hash='hev1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='ev2', address_hash='hev2', raw_value='B', normalized_value='b'))
        base_edge = uow.edges.add(
            Edge(
                edge_uid='edge-evidence-1',
                source_node_id=1,
                target_node_id=2,
                edge_family='relation',
                connect_type='neutral',
                relation_detail={},
                trust_score=0.9,
                support_count=1,
                conflict_count=0,
                contradiction_pressure=0.0,
            )
        )
        RevisionEdgeService().record_conflict_assertion(
            uow,
            base_edge=base_edge,
            reason='strong_conflict_signal',
            signal_score=0.95,
            message_id=None,
        )
        uow.commit()

    custom_rules = (
        RevisionExecutionRule(
            name='relation-neutral-evidence-first',
            edge_families=('relation',),
            connect_types=('neutral',),
            marker_conflict_support_threshold_for_deactivate=10,
            marker_conflict_evidence_threshold_for_deactivate=2.0,
        ),
        RevisionExecutionRule(name='fallback'),
    )
    service = StructureRevisionService(execution_rules=custom_rules)

    with uow_factory() as uow:
        actions = service.review_candidates(uow, message_id=None, limit=20)
        uow.commit()
        matched = [action for action in actions if action.edge_id == (base_edge.id or 0)]
        assert matched
        assert matched[0].action == 'edge_deactivated'
        evidence = (matched[0].metadata or {}).get('marker_evidence', {})
        assert float(evidence.get('conflict_support', 0.0)) >= 2.0


def test_structure_revision_applies_rule_overrides_on_default_rules(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)

    with uow_factory() as uow:
        uow.nodes.add(Node(node_uid='ov1', address_hash='hov1', raw_value='A', normalized_value='a'))
        uow.nodes.add(Node(node_uid='ov2', address_hash='hov2', raw_value='B', normalized_value='b'))
        base_edge = uow.edges.add(
            Edge(
                edge_uid='edge-override-1',
                source_node_id=1,
                target_node_id=2,
                edge_family='relation',
                connect_type='neutral',
                relation_detail={},
                trust_score=0.9,
                support_count=1,
                conflict_count=0,
                contradiction_pressure=0.0,
            )
        )
        RevisionEdgeService().record_conflict_assertion(
            uow,
            base_edge=base_edge,
            reason='override_check',
            signal_score=0.95,
            message_id=None,
        )
        uow.commit()

    service = StructureRevisionService(
        rule_overrides={
            'relation_neutral': {
                'marker_conflict_support_threshold_for_deactivate': 10,
                'marker_conflict_evidence_threshold_for_deactivate': 2.0,
            }
        }
    )
    with uow_factory() as uow:
        actions = service.review_candidates(uow, message_id=None, limit=20)
        uow.commit()
        matched = [action for action in actions if action.edge_id == (base_edge.id or 0)]
        assert matched
        assert matched[0].action == 'edge_deactivated'
