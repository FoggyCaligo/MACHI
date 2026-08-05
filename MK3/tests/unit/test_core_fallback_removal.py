from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from core.cognition.direct_node_accessor import DirectNodeAccessor
from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.cognition.meaning_block import MeaningBlock
from core.entities.intent import IntentSnapshot
from core.entities.node import Node
from core.entities.thought_view import ThoughtView
from core.thinking.conclusion_builder import ConclusionBuilder, MissingIntentSnapshotError
from tools.prompt_loader import load_prompt_text


class FakeHashResolver:
    def address_for(self, block: MeaningBlock) -> str:
        return f'addr:{block.normalized_text}'


class FakeNodeRepository:
    def __init__(self, *, direct: Node | None = None, fallback: list[Node] | None = None) -> None:
        self.direct = direct
        self.fallback = fallback or []
        self.normalized_lookup_called = False

    def get_by_address_hash(self, address_hash: str) -> Node | None:
        return self.direct

    def search_by_normalized_value(self, *_args, **_kwargs) -> list[Node]:
        self.normalized_lookup_called = True
        return list(self.fallback)


@dataclass(slots=True)
class FakeRequest:
    session_id: str = 's1'
    message_id: int | None = 1
    message_text: str = '질문입니다.'


def test_direct_node_accessor_uses_address_hash_only() -> None:
    accessor = DirectNodeAccessor(FakeHashResolver())
    block = MeaningBlock(text='찰갑', normalized_text='찰갑', block_kind='noun_phrase', sentence_index=0, block_index=0, source_sentence='찰갑')
    repo = FakeNodeRepository(
        direct=None,
        fallback=[Node(id=99, raw_value='찰갑', normalized_value='찰갑', node_kind='noun_phrase')],
    )

    result = accessor.resolve(repo, block)

    assert result.node is None
    assert result.reused_via is None
    assert repo.normalized_lookup_called is False


def test_conclusion_builder_requires_intent_snapshot() -> None:
    builder = ConclusionBuilder()
    with pytest.raises(MissingIntentSnapshotError):
        builder.build(
            request=FakeRequest(),
            thought_view=ThoughtView(session_id='s1', message_text='질문입니다.'),
            contradiction_signals=[],
            trust_updates=[],
            revision_actions=[],
            intent_snapshot=None,
        )


def test_conclusion_builder_accepts_explicit_intent_snapshot() -> None:
    builder = ConclusionBuilder()
    conclusion = builder.build(
        request=FakeRequest(),
        thought_view=ThoughtView(session_id='s1', message_text='질문입니다.'),
        contradiction_signals=[],
        trust_updates=[],
        revision_actions=[],
        intent_snapshot=IntentSnapshot(
            drive_name='user_delight',
            live_intent='graph_grounded_reasoning',
            snapshot_intent='graph_grounded_reasoning',
            sufficiency_score=0.5,
            stop_threshold=0.62,
            should_stop=False,
        ),
    )

    assert conclusion.inferred_intent == 'graph_grounded_reasoning'


def test_prompt_loader_resolves_from_project_root_even_when_cwd_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    text = load_prompt_text('prompts/system/chat_system_prompt.txt')
    assert text


def test_input_segmenter_does_not_force_statement_fallback_for_punctuation_only_input() -> None:
    segmenter = InputSegmenter(hash_resolver=HashResolver())
    blocks = segmenter.segment('!!!')
    assert blocks == []


def test_input_segmenter_does_not_drop_tokens_via_stopword_list() -> None:
    segmenter = InputSegmenter(hash_resolver=HashResolver())
    blocks = segmenter.segment('그리고 지금 기준을 정리해줘.')
    normalized = [block.normalized_text for block in blocks if block.block_kind == 'noun_phrase']
    assert '그리고' in normalized
    assert '지금' in normalized
    assert '기준' in normalized


def test_hash_resolver_distinguishes_structural_scope_for_same_text() -> None:
    resolver = HashResolver()
    sentence_block = MeaningBlock(
        text='갑옷',
        normalized_text='갑옷',
        block_kind='statement_phrase',
        sentence_index=0,
        block_index=0,
        source_sentence='갑옷',
        metadata={'source': 'sentence_structure'},
    )
    token_block = MeaningBlock(
        text='갑옷',
        normalized_text='갑옷',
        block_kind='noun_phrase',
        sentence_index=0,
        block_index=1,
        source_sentence='갑옷',
        metadata={'source': 'token_rule'},
    )

    assert resolver.address_for(sentence_block) != resolver.address_for(token_block)
