from __future__ import annotations

from dataclasses import dataclass, field

from core.cognition.meaning_block import MeaningBlock
from core.entities.chat_message import ChatMessage
from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.thought_view import ActivatedNode, ThoughtView
from core.thinking.intent_manager import IntentManager


@dataclass
class FakeChatMessages:
    rows: list[ChatMessage] = field(default_factory=list)

    def list_by_session(self, session_id: str, *, limit: int = 100, before_turn_index=None, after_turn_index=None):
        return [row for row in self.rows if row.session_id == session_id][-limit:]


@dataclass
class FakeGraphEvents:
    events: list = field(default_factory=list)

    def add(self, event):
        self.events.append(event)
        return event


@dataclass
class FakeUOW:
    chat_messages: FakeChatMessages
    graph_events: FakeGraphEvents


@dataclass(slots=True)
class Request:
    session_id: str
    message_id: int | None = None
    message_text: str = ''


def _block(text: str, kind: str, index: int = 0) -> MeaningBlock:
    return MeaningBlock(
        text=text,
        normalized_text=text,
        block_kind=kind,
        sentence_index=0,
        block_index=index,
        source_sentence=text,
        metadata={},
    )


def _node(node_id: int) -> Node:
    return Node(
        id=node_id,
        node_uid=f'node_{node_id}',
        address_hash=f'hash_{node_id}',
        node_kind='node',
        raw_value=f'value_{node_id}',
        normalized_value=f'value_{node_id}',
        trust_score=0.7,
        stability_score=0.6,
    )


def _edge(edge_id: int, source: int, target: int) -> Edge:
    return Edge(
        id=edge_id,
        edge_uid=f'edge_{edge_id}',
        source_node_id=source,
        target_node_id=target,
        edge_family='relation',
        connect_type='neutral',
        relation_detail={'note': 'fixture relation edge'},
        edge_weight=0.4,
        support_count=1,
        conflict_count=0,
        contradiction_pressure=0.0,
        trust_score=0.7,
        is_active=True,
    )


def _view(*, pointers=0, edges=0, patterns=0, seed_ids=(1,), node_ids=(1,)) -> ThoughtView:
    seed_nodes = [ActivatedNode(node=_node(node_id), activation_score=0.8, activated_by='seed') for node_id in seed_ids]
    nodes = [_node(node_id) for node_id in node_ids]
    edge_rows = [_edge(i + 1, node_ids[0], node_ids[min(1, len(node_ids)-1)]) for i in range(edges)] if edges else []
    pointer_rows = [type('Pointer', (), {'id': i + 1})() for i in range(pointers)]
    activated_patterns = [type('Pattern', (), {'pattern_name': f'p{i}'})() for i in range(patterns)]
    blocks = [_block('stmt', 'statement_phrase', 0)]
    return ThoughtView(
        session_id='s1',
        message_text='msg',
        seed_blocks=blocks,
        seed_nodes=seed_nodes,
        nodes=nodes,
        edges=edge_rows,
        pointers=pointer_rows,
        activated_patterns=activated_patterns,
        metadata={},
    )


def test_intent_manager_prefers_structure_review_on_contradiction() -> None:
    manager = IntentManager()
    uow = FakeUOW(chat_messages=FakeChatMessages(), graph_events=FakeGraphEvents())
    snapshot = manager.resolve(
        uow,
        request=Request(session_id='s1', message_id=1, message_text='msg'),
        thought_view=_view(edges=2, node_ids=(1, 2)),
        contradiction_signals=[object()],
        trust_updates=[],
        revision_actions=[],
    )
    assert snapshot.snapshot_intent == 'structure_review'
    assert snapshot.shifted is False
    assert snapshot.should_stop is False
    assert uow.graph_events.events[-1].event_type == 'intent_snapshot_decided'


def test_intent_manager_keeps_previous_intent_when_overlap_continues() -> None:
    previous_assistant = ChatMessage(
        id=10,
        message_uid='m10',
        session_id='s1',
        turn_index=1,
        role='assistant',
        content='prev',
        metadata={
            'intent_snapshot': {
                'snapshot_intent': 'relation_synthesis_request',
                'shifted': False,
                'sufficiency_score': 0.71,
                'topic_terms': ['value_1', 'value_2'],
                'tone_hint': 'steady_plain_korean',
                'metadata': {'activated_concepts': [1, 2, 3]},
            }
        },
    )
    manager = IntentManager()
    uow = FakeUOW(chat_messages=FakeChatMessages(rows=[previous_assistant]), graph_events=FakeGraphEvents())
    snapshot = manager.resolve(
        uow,
        request=Request(session_id='s1', message_id=11, message_text='msg'),
        thought_view=_view(edges=4, patterns=1, seed_ids=(1, 2), node_ids=(1, 2, 3)),
        contradiction_signals=[],
        trust_updates=[],
        revision_actions=[],
    )
    assert snapshot.snapshot_intent == 'relation_synthesis_request'
    assert snapshot.continuation is True
    assert snapshot.previous_snapshot_intent == 'relation_synthesis_request'
    assert snapshot.topic_continuity in {'continued_topic', 'related_topic'}
    assert snapshot.topic_overlap_count >= 1
    assert snapshot.tone_hint == 'steady_plain_korean'


def test_intent_manager_shifts_to_structure_review_when_previous_path_breaks() -> None:
    previous_assistant = ChatMessage(
        id=20,
        message_uid='m20',
        session_id='s1',
        turn_index=2,
        role='assistant',
        content='prev',
        metadata={
            'intent_snapshot': {
                'snapshot_intent': 'graph_grounded_reasoning',
                'shifted': False,
                'sufficiency_score': 0.80,
                'topic_terms': ['value_9'],
                'metadata': {'activated_concepts': [1]},
            }
        },
    )
    manager = IntentManager()
    uow = FakeUOW(chat_messages=FakeChatMessages(rows=[previous_assistant]), graph_events=FakeGraphEvents())
    snapshot = manager.resolve(
        uow,
        request=Request(session_id='s1', message_id=21, message_text='msg'),
        thought_view=_view(edges=1, node_ids=(1, 2)),
        contradiction_signals=[object()],
        trust_updates=[object()],
        revision_actions=[],
    )
    assert snapshot.snapshot_intent == 'open_information_request'
    assert snapshot.shifted is True
    assert snapshot.shift_reason == 'topic_shift_intent_reset:new_info_needed'
    assert snapshot.topic_continuity == 'shifted_topic'


def test_conflict_connect_type_triggers_contradiction_without_contradicts_semantics() -> None:
    from core.entities.edge import Edge
    from core.entities.thought_view import ThoughtView
    from core.thinking.contradiction_detector import ContradictionDetector

    edge = Edge(
        id=99,
        source_node_id=1,
        target_node_id=2,
        edge_family='relation',
        connect_type='conflict',
        support_count=0,
        conflict_count=1,
        contradiction_pressure=1.1,
        trust_score=0.5,
    )
    thought_view = ThoughtView(session_id='s1', message_text='x', nodes=[], edges=[edge], pointers=[])

    signals = ContradictionDetector().inspect(thought_view)

    assert len(signals) == 1
    assert signals[0].reason in {
        'relation_conflict_connect_type',
        'conflict_connect_type',
        'medium_contradiction_pressure',
        'conflict_outweighs_support',
    }


def test_conflict_connect_type_triggers_contradiction_without_conflict_counters() -> None:
    from core.entities.edge import Edge
    from core.entities.thought_view import ThoughtView
    from core.thinking.contradiction_detector import ContradictionDetector

    edge = Edge(
        id=100,
        source_node_id=1,
        target_node_id=2,
        edge_family='relation',
        connect_type='conflict',
        support_count=1,
        conflict_count=0,
        contradiction_pressure=0.0,
        trust_score=0.7,
    )
    thought_view = ThoughtView(session_id='s1', message_text='x', nodes=[], edges=[edge], pointers=[])

    signals = ContradictionDetector().inspect(thought_view)

    assert len(signals) == 1
    assert signals[0].reason in {'relation_conflict_connect_type', 'conflict_connect_type'}
