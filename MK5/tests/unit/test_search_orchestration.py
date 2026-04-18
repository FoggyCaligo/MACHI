from __future__ import annotations

from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ThoughtView
from core.search.search_need_evaluator import SearchNeedEvaluator
from core.search.search_query_planner import SearchQueryPlanner
from core.search.search_sidecar import SearchBackendResult, SearchEvidence, SearchSidecar


class FakeBackend:
    def search(self, query: str, *, max_results: int, timeout_seconds: float):
        return SearchBackendResult(
            results=[
                SearchEvidence(
                    title=query,
                    snippet='snippet',
                    passages=[f'{query} evidence passage'],
                    url=f'https://example.test/{query}',
                    provider='fake-backend',
                )
            ]
        )


def _blocks(message: str):
    return InputSegmenter(hash_resolver=HashResolver()).segment(message)


def test_search_need_evaluator_uses_final_statement_noun_phrases() -> None:
    view = ThoughtView(
        session_id='s1',
        message_text='안녕? 글록에 대해 알려줄래?',
        seed_blocks=_blocks('안녕? 글록에 대해 알려줄래?'),
        seed_nodes=[],
        nodes=[],
        edges=[],
        pointers=[],
        metadata={},
    )
    decision = SearchNeedEvaluator().evaluate(
        message=view.message_text,
        thought_view=view,
        conclusion=CoreConclusion(session_id='s1', message_id=1, user_input_summary=view.message_text, inferred_intent='open_information_request'),
    )
    assert '글록' in decision.target_terms
    assert '안녕' not in decision.target_terms
    assert decision.need_search is True


def test_search_query_planner_emits_individual_concept_queries() -> None:
    decision = SearchNeedEvaluator().evaluate(
        message='글록에 대해 알려줄래?',
        thought_view=ThoughtView(session_id='s1', message_text='글록에 대해 알려줄래?', seed_blocks=_blocks('글록에 대해 알려줄래?'), seed_nodes=[], nodes=[], edges=[], pointers=[], metadata={}),
        conclusion=CoreConclusion(session_id='s1', message_id=1, user_input_summary='글록에 대해 알려줄래?', inferred_intent='open_information_request'),
    )
    plan = SearchQueryPlanner().plan(
        model_name='gemma3:4b',
        message='글록에 대해 알려줄래?',
        thought_view=ThoughtView(session_id='s1', message_text='글록에 대해 알려줄래?', seed_blocks=_blocks('글록에 대해 알려줄래?'), seed_nodes=[], nodes=[], edges=[], pointers=[], metadata={}),
        conclusion=CoreConclusion(session_id='s1', message_id=1, user_input_summary='글록에 대해 알려줄래?', inferred_intent='open_information_request'),
        decision=decision,
    )
    assert plan.queries[0] == '글록'


def test_search_sidecar_runs_without_scope_gate_or_slot_planner() -> None:
    view = ThoughtView(
        session_id='s1',
        message_text='글록에 대해 알려줄래?',
        seed_blocks=_blocks('글록에 대해 알려줄래?'),
        seed_nodes=[],
        nodes=[],
        edges=[],
        pointers=[],
        metadata={},
    )
    conclusion = CoreConclusion(session_id='s1', message_id=1, user_input_summary=view.message_text, inferred_intent='open_information_request')
    run = SearchSidecar(backend=FakeBackend()).run(
        message=view.message_text,
        thought_view=view,
        conclusion=conclusion,
        model_name='gemma3:4b',
    )
    assert run.attempted is True
    assert run.plan is not None
    assert run.plan.queries[0] == '글록'
    assert run.results
    assert run.slot_plan is None
