from __future__ import annotations

from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.cognition.hash_resolver import HashResolver
from core.cognition.meaning_block import MeaningBlock
from core.entities.chat_message import ChatMessage
from core.entities.intent import IntentSnapshot
from core.entities.node import Node


class FakeNodesRepo:
    def __init__(self, nodes: list[Node], hash_map: dict[str, Node]) -> None:
        self.nodes = nodes
        self.hash_map = hash_map

    def find_by_address_hashes(self, address_hashes):
        return []

    def get_by_address_hash(self, address_hash):
        return self.hash_map.get(address_hash)

    def find_by_normalized_values(self, normalized_values, *, node_kinds=None, limit=24):
        values = set(normalized_values or [])
        return [node for node in self.nodes if node.normalized_value in values][:limit]

    def list_by_ids(self, node_ids):
        allowed = set(node_ids or [])
        return [node for node in self.nodes if node.id in allowed]


class FakeEdgesRepo:
    def list_edges_for_nodes(self, node_ids, *, active_only=True):
        return []


class FakePointersRepo:
    def list_by_owner(self, owner_id, *, active_only=True):
        return []


class FakeChatMessages:
    def __init__(self, rows):
        self.rows = rows

    def list_by_session(self, session_id: str, *, limit: int = 100, before_turn_index=None, after_turn_index=None):
        return [row for row in self.rows if row.session_id == session_id][-limit:]


class FakeUOW:
    def __init__(self, nodes, messages, hash_map):
        self.nodes = FakeNodesRepo(nodes, hash_map)
        self.edges = FakeEdgesRepo()
        self.node_pointers = FakePointersRepo()
        self.chat_messages = FakeChatMessages(messages)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _node(node_id: int, value: str) -> Node:
    return Node(
        id=node_id,
        node_uid=f'node_{node_id}',
        address_hash=f'hash_{node_id}',
        node_kind='noun_phrase',
        raw_value=value,
        normalized_value=value,
        trust_score=0.8,
        stability_score=0.7,
    )


class StubSegmenter:
    def segment(self, content: str):
        return [
            MeaningBlock(
                text='plate armor',
                normalized_text='plate armor',
                block_kind='noun_phrase',
                sentence_index=0,
                block_index=0,
                source_sentence=content,
                metadata={},
            ),
            MeaningBlock(
                text='mail armor',
                normalized_text='mail armor',
                block_kind='noun_phrase',
                sentence_index=0,
                block_index=1,
                source_sentence=content,
                metadata={},
            ),
        ]


def test_activation_engine_carries_previous_topic_and_tone_metadata() -> None:
    previous_snapshot = IntentSnapshot(
        snapshot_intent='relation_synthesis_request',
        topic_terms=['plate armor', 'mail armor'],
        topic_continuity='continued_topic',
        topic_overlap_count=2,
        tone_hint='steady_plain_korean',
    )
    assistant_message = ChatMessage(
        id=1,
        message_uid='m1',
        session_id='s1',
        turn_index=1,
        role='assistant',
        content='previous',
        metadata={'intent_snapshot': previous_snapshot.to_metadata()},
    )
    nodes = [_node(1, 'plate armor'), _node(2, 'mail armor')]
    segmenter = StubSegmenter()
    resolver = HashResolver()
    hash_map = {}
    for block, node in zip(segmenter.segment('plate armor and mail armor'), nodes):
        hash_map[resolver.address_for(block)] = node
    engine = ActivationEngine(lambda: FakeUOW(nodes, [assistant_message], hash_map), segmenter=segmenter)

    thought_view = engine.build_view(ActivationRequest(session_id='s1', content='plate armor and mail armor'))

    assert thought_view.metadata['previous_topic_terms'] == ['plate armor', 'mail armor']
    assert thought_view.metadata['previous_tone_hint'] == 'steady_plain_korean'
    assert 'plate armor' in thought_view.metadata['current_topic_terms']
    assert thought_view.metadata['topic_overlap_count'] >= 1
    assert thought_view.metadata['recent_memory_count'] >= 1
    assert thought_view.metadata['recent_memory_messages'][-1]['role'] == 'assistant'
