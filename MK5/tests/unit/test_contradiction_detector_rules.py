from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.edge import Edge
from core.entities.thought_view import ThoughtView
from core.thinking.contradiction_detector import ContradictionDetector


def test_contradiction_detector_distinguishes_concept_vs_relation_conflict_reason() -> None:
    concept_edge = Edge(
        id=1,
        edge_uid='c1',
        source_node_id=1,
        target_node_id=2,
        edge_family='concept',
        connect_type='conflict',
        relation_detail={'kind': 'conflict_assertion'},
        support_count=1,
        conflict_count=0,
        contradiction_pressure=0.0,
        trust_score=0.9,
        is_active=True,
    )
    relation_edge = Edge(
        id=2,
        edge_uid='r1',
        source_node_id=3,
        target_node_id=4,
        edge_family='relation',
        connect_type='conflict',
        relation_detail={'kind': 'conflict_assertion'},
        support_count=1,
        conflict_count=0,
        contradiction_pressure=0.0,
        trust_score=0.9,
        is_active=True,
    )
    view = ThoughtView(session_id='s', message_text='x', edges=[concept_edge, relation_edge])
    signals = ContradictionDetector().inspect(view)
    by_edge = {item.edge_id: item for item in signals}
    assert by_edge[1].reason == 'concept_conflict_connect_type'
    assert by_edge[2].reason == 'relation_conflict_connect_type'


def test_contradiction_detector_raises_opposite_hierarchy_conflict_reason() -> None:
    edge = Edge(
        id=10,
        edge_uid='o1',
        source_node_id=1,
        target_node_id=2,
        edge_family='concept',
        connect_type='opposite',
        relation_detail={'kind': 'subtype_of'},
        support_count=1,
        conflict_count=0,
        contradiction_pressure=0.0,
        trust_score=0.95,
        is_active=True,
    )
    view = ThoughtView(session_id='s', message_text='x', edges=[edge])
    signals = ContradictionDetector().inspect(view)
    assert signals
    assert signals[0].reason == 'opposite_hierarchy_conflict'
