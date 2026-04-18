from __future__ import annotations

from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ThoughtView
from core.search.search_need_evaluator import SearchNeedEvaluator
from core.verbalization.verbalizer import Verbalizer


def test_current_turn_nodes_do_not_count_as_grounding() -> None:
    current_node = Node(
        id=1,
        raw_value='글록',
        normalized_value='글록',
        node_kind='concept',
        created_from_event_id=123,
        payload={'source_type': 'search', 'claim_domain': 'world_fact'},
    )
    view = ThoughtView(
        session_id='s1',
        message_text='글록에 대해 알려줄래?',
        seed_blocks=[],
        seed_nodes=[],
        nodes=[current_node],
        edges=[],
        pointers=[],
        metadata={'current_root_event_id': 123},
    )
    decision = SearchNeedEvaluator().evaluate(
        message='글록에 대해 알려줄래?',
        thought_view=view,
        conclusion=CoreConclusion(session_id='s1', message_id=1, user_input_summary='글록에 대해 알려줄래?', inferred_intent='open_information_request'),
    )
    assert decision.need_search is False or '글록' not in decision.metadata.get('grounded_terms', [])


def test_verbalizer_forces_boundary_response_without_grounded_evidence() -> None:
    conclusion = CoreConclusion(
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
