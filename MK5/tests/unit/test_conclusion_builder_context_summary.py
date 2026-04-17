from __future__ import annotations

from core.entities.intent import IntentSnapshot
from core.entities.node import Node
from core.entities.thought_view import ActivatedNode, ThoughtView
from core.thinking.conclusion_builder import ConclusionBuilder


class FakeRequest:
    session_id = 's1'
    message_id = 1
    message_text = '안녕? 단테의 신곡에 대해 알려줄래?'


def _build_thought_view() -> ThoughtView:
    seed = ActivatedNode(
        node=Node(id=1, raw_value='단테의 신곡', normalized_value='단테의 신곡', node_kind='noun_phrase'),
        activation_score=1.0,
        activated_by='seed',
    )
    return ThoughtView(
        session_id='s1',
        message_text=FakeRequest.message_text,
        seed_nodes=[seed],
        nodes=[seed.node],
        edges=[],
        metadata={'topic_overlap_count': 0, 'recent_memory_count': 3},
    )


def test_current_turn_activation_does_not_claim_existing_context() -> None:
    builder = ConclusionBuilder()

    conclusion = builder.build(
        request=FakeRequest(),
        thought_view=_build_thought_view(),
        contradiction_signals=[],
        trust_updates=[],
        revision_actions=[],
        intent_snapshot=IntentSnapshot(
            snapshot_intent='graph_grounded_reasoning',
            topic_continuity='related_topic',
            topic_overlap_count=0,
            shifted=False,
            should_stop=False,
        ),
    )

    assert '기존 맥락이 일부 있어' not in conclusion.explanation_summary
    assert '현재 활성화된 단서를 바탕으로' in conclusion.explanation_summary
    assert '겹치는 단서가 조금 있지만' in conclusion.explanation_summary


def test_strong_prior_overlap_keeps_existing_context_summary() -> None:
    builder = ConclusionBuilder()
    thought_view = _build_thought_view()
    thought_view.metadata['topic_overlap_count'] = 2

    conclusion = builder.build(
        request=FakeRequest(),
        thought_view=thought_view,
        contradiction_signals=[],
        trust_updates=[],
        revision_actions=[],
        intent_snapshot=IntentSnapshot(
            snapshot_intent='graph_grounded_reasoning',
            topic_continuity='related_topic',
            topic_overlap_count=2,
            shifted=False,
            should_stop=False,
        ),
    )

    assert '기존 맥락이 일부 있어' in conclusion.explanation_summary
