from __future__ import annotations

import json

from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ActivatedNode, ThoughtView
from core.search.search_need_evaluator import SearchNeedEvaluator
from core.search.search_query_planner import SearchQueryPlanner
from core.search.search_sidecar import SearchBackendResult, SearchEvidence, SearchSidecar, TrustedSearchBackend


class FakeChatResult:
    def __init__(self, content: str) -> None:
        self.content = content
        self.model = 'fake-model'
        self.raw = {}


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.last_messages = None
        self.last_model = None
        self.last_format = None

    def chat(self, *, model_name, messages, stream=False, options=None, response_format=None):
        self.last_messages = messages
        self.last_model = model_name
        self.last_format = response_format
        return FakeChatResult(self.content)


class FakeBackend:
    def search(self, query: str, *, max_results: int, timeout_seconds: float):
        return SearchBackendResult(
            results=[
                SearchEvidence(
                    title=query,
                    snippet='result',
                    url=f'https://example.test/{query}',
                    provider='fake-backend',
                    trust_hint=0.77,
                    source_provenance='trusted_search',
                )
            ],
            errors=[],
        )


class FakeProvider:
    def __init__(self, name: str, items: list[SearchEvidence], fail: bool = False) -> None:
        self.provider_name = name
        self.items = items
        self.fail = fail

    def search(self, query: str, *, max_results: int, timeout_seconds: float):
        if self.fail:
            raise RuntimeError('network down')
        return self.items[:max_results]


def _thought_view() -> ThoughtView:
    node1 = Node(id=1, raw_value='찰갑', normalized_value='찰갑', node_kind='concept')
    node2 = Node(id=2, raw_value='미늘갑옷', normalized_value='미늘갑옷', node_kind='concept')
    node3 = Node(id=3, raw_value='사슬갑옷', normalized_value='사슬갑옷', node_kind='concept')
    return ThoughtView(
        session_id='s1',
        message_text='찰갑과 미늘갑옷, 사슬갑옷에 대한 차이점을 정리해줄래?',
        seed_nodes=[
            ActivatedNode(node=node1, activation_score=0.9, activated_by='seed'),
            ActivatedNode(node=node2, activation_score=0.88, activated_by='seed'),
            ActivatedNode(node=node3, activation_score=0.86, activated_by='seed'),
        ],
        nodes=[node1, node2, node3],
    )


def _conclusion() -> CoreConclusion:
    return CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='찰갑과 미늘갑옷, 사슬갑옷에 대한 차이점을 정리해줄래?',
        inferred_intent='relation_synthesis_request',
        activated_concepts=[1, 2, 3],
        key_relations=[1],
        explanation_summary='질문에 바로 답하기 전에 현재 주제의 외부 근거를 확인할 필요가 있다.',
    )


def test_search_need_evaluator_uses_task_kind_and_scope_grounding() -> None:
    decision = SearchNeedEvaluator().evaluate(
        message='찰갑과 미늘갑옷, 사슬갑옷에 대한 차이점을 정리해줄래?',
        thought_view=_thought_view(),
        conclusion=_conclusion(),
    )
    assert decision.need_search is True
    assert '찰갑' in decision.target_terms
    assert '미늘갑옷' in decision.target_terms
    assert decision.reason == 'open_request_without_external_grounding'


def test_search_query_planner_returns_grounding_and_comparison_queries() -> None:
    client = FakeClient(json.dumps({
        'grounding_queries': ['찰갑 갑옷', '미늘갑옷 갑옷', '사슬갑옷 갑옷'],
        'comparison_queries': ['찰갑 미늘갑옷 차이', '미늘갑옷 사슬갑옷 차이'],
        'reason': '개별 grounding 후 비교',
        'focus_terms': ['찰갑', '미늘갑옷', '사슬갑옷'],
    }))
    planner = SearchQueryPlanner(client=client)
    plan = planner.plan(
        model_name='gemma4:e2b',
        message='찰갑과 미늘갑옷, 사슬갑옷에 대한 차이점을 정리해줄래?',
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        decision=SearchNeedEvaluator().evaluate(
            message='찰갑과 미늘갑옷, 사슬갑옷에 대한 차이점을 정리해줄래?',
            thought_view=_thought_view(),
            conclusion=_conclusion(),
        ),
    )
    assert plan.queries[:3] == ['찰갑 갑옷', '미늘갑옷 갑옷', '사슬갑옷 갑옷']
    assert client.last_format == 'json'
    prompt = client.last_messages[1]['content']
    assert '찰갑' in prompt
    assert '미늘갑옷' in prompt
    assert '사슬갑옷' in prompt


def test_trusted_search_backend_dedups_preserves_trust_and_reports_errors() -> None:
    backend = TrustedSearchBackend(
        providers=[
            FakeProvider('broken-provider', [], fail=True),
            FakeProvider(
                'provider-a',
                [
                    SearchEvidence(
                        title='찰갑',
                        snippet='a',
                        url='https://example.test/a',
                        provider='provider-a',
                        trust_hint=0.91,
                        source_provenance='trusted_search',
                    )
                ],
            ),
            FakeProvider(
                'provider-b',
                [
                    SearchEvidence(
                        title='찰갑',
                        snippet='dup',
                        url='https://example.test/a',
                        provider='provider-b',
                        trust_hint=0.61,
                        source_provenance='trusted_search',
                    ),
                    SearchEvidence(
                        title='미늘갑옷',
                        snippet='b',
                        url='https://example.test/b',
                        provider='provider-b',
                        trust_hint=0.61,
                        source_provenance='trusted_search',
                    ),
                ],
            ),
        ]
    )
    outcome = backend.search('갑옷 비교', max_results=4, timeout_seconds=1.0)
    assert len(outcome.results) == 2
    assert outcome.results[0].provider == 'provider-a'
    assert outcome.results[0].trust_hint == 0.91
    assert outcome.results[0].metadata['source_provenance'] == 'trusted_search'
    assert any('broken-provider' in item for item in outcome.errors)


def test_search_sidecar_runs_multi_query_plan_then_backend() -> None:
    client = FakeClient(json.dumps({
        'grounding_queries': ['찰갑 갑옷', '미늘갑옷 갑옷', '사슬갑옷 갑옷'],
        'comparison_queries': ['찰갑 미늘갑옷 차이'],
        'reason': '개별 grounding 후 비교',
        'focus_terms': ['찰갑', '미늘갑옷', '사슬갑옷'],
    }))
    sidecar = SearchSidecar(query_planner=SearchQueryPlanner(client=client), backend=FakeBackend())
    result = sidecar.run(
        message='찰갑과 미늘갑옷, 사슬갑옷에 대한 차이점을 정리해줄래?',
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        model_name='gemma4:e2b',
    )
    assert result.attempted is True
    assert result.plan is not None
    assert result.plan.queries[:3] == ['찰갑 갑옷', '미늘갑옷 갑옷', '사슬갑옷 갑옷']
    assert len(result.results) >= 3
    assert result.results[0].metadata['planned_query'] == '찰갑 갑옷'
