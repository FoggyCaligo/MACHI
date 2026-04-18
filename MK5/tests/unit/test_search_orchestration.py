from __future__ import annotations

from core.cognition.hash_resolver import HashResolver
from core.cognition.input_segmenter import InputSegmenter
from core.entities.node import Node
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
    blocks = InputSegmenter(hash_resolver=HashResolver()).segment(message)
    for block in blocks:
        if block.block_kind != 'noun_phrase':
            continue
        if block.normalized_text == '안녕':
            block.metadata.update({'importance': 'background', 'search_policy': 'ignore', 'freshness_kind': 'unknown'})
        else:
            block.metadata.update({'importance': 'primary', 'search_policy': 'search_if_unusable', 'freshness_kind': 'timeless'})
    return blocks


def test_search_need_evaluator_uses_meaning_unit_labels() -> None:
    blocks = _blocks('안녕? 글록에 대해 알려줄래?')
    decision = SearchNeedEvaluator().evaluate(
        message='안녕? 글록에 대해 알려줄래?',
        meaning_blocks=blocks,
        resolved_nodes={},
        current_root_event_id=123,
    )
    assert '글록' in decision.target_terms
    assert '안녕' not in decision.target_terms
    assert decision.need_search is True


def test_search_query_planner_emits_individual_meaning_queries() -> None:
    blocks = _blocks('글록에 대해 알려줄래?')
    decision = SearchNeedEvaluator().evaluate(
        message='글록에 대해 알려줄래?',
        meaning_blocks=blocks,
        resolved_nodes={},
        current_root_event_id=123,
    )
    plan = SearchQueryPlanner().plan(
        model_name='gemma3:4b',
        message='글록에 대해 알려줄래?',
        decision=decision,
    )
    assert plan.queries[0] == '글록'


def test_search_sidecar_runs_without_legacy_slot_planner() -> None:
    blocks = _blocks('글록에 대해 알려줄래?')
    run = SearchSidecar(backend=FakeBackend()).run(
        message='글록에 대해 알려줄래?',
        meaning_blocks=blocks,
        resolved_nodes={},
        current_root_event_id=123,
        model_name='gemma3:4b',
    )
    assert run.attempted is True
    assert run.plan is not None
    assert run.plan.queries[0] == '글록'
    assert run.results
