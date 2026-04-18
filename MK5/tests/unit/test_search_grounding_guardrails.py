from __future__ import annotations

from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.entities.node import Node
from core.search.search_need_evaluator import SearchNeedEvaluator
from core.verbalization.verbalizer import Verbalizer


def _blocks(message: str):
    blocks = InputSegmenter(hash_resolver=HashResolver()).segment(message)
    for block in blocks:
        if block.block_kind == 'noun_phrase':
            block.metadata.update({'importance': 'primary', 'search_policy': 'search_if_unusable', 'freshness_kind': 'timeless'})
    return blocks


def test_current_turn_nodes_do_not_count_as_usable_grounding() -> None:
    current_node = Node(
        id=1,
        raw_value='글록',
        normalized_value='글록',
        node_kind='concept',
        created_from_event_id=123,
        payload={'source_type': 'search', 'claim_domain': 'world_fact'},
    )
    decision = SearchNeedEvaluator().evaluate(
        message='글록에 대해 알려줄래?',
        meaning_blocks=_blocks('글록에 대해 알려줄래?'),
        resolved_nodes={'글록': current_node},
        current_root_event_id=123,
    )
    assert decision.need_search is True
    assert '글록' in decision.metadata.get('missing_terms', [])


def test_verbalizer_forces_boundary_response_without_grounded_evidence() -> None:
    conclusion = __import__('core.entities.conclusion', fromlist=['CoreConclusion']).CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='글록에 대해 알려줄래?',
        inferred_intent='open_information_request',
        metadata={
            'search_context': {
                'need_search': True,
                'attempted': False,
                'result_count': 0,
                'grounded_terms': [],
                'missing_terms': ['글록'],
                'missing_aspects': [],
                'error': '',
                'no_evidence_found': False,
            }
        },
    )
    result = Verbalizer().verbalize(conclusion, model_name='gemma3:4b')
    assert '현재 확보된 근거만으로는' in result.user_response
    assert result.used_llm is False
