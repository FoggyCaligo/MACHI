from __future__ import annotations

import json

from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ActivatedNode, ThoughtView
from core.search.search_need_evaluator import SearchNeedEvaluator
from core.search.search_query_planner import SearchQueryPlanner
from core.search.search_sidecar import SearchEvidence, SearchSidecar


class FakeChatResult:
    def __init__(self, content: str) -> None:
        self.content = content


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
        return [
            SearchEvidence(
                title=query,
                snippet='result',
                url=f'https://example.test/{query}',
                provider='fake-backend',
            )
        ]


def _thought_view() -> ThoughtView:
    node1 = Node(id=1, raw_value='찰갑', normalized_value='찰갑', node_kind='concept')
    node2 = Node(id=2, raw_value='체인메일', normalized_value='체인메일', node_kind='concept')
    return ThoughtView(
        session_id='s1',
        message_text='이 두 갑옷에 대해 우선 검색부터 해줄래?',
        seed_nodes=[
            ActivatedNode(node=node1, activation_score=0.9, activated_by='seed'),
            ActivatedNode(node=node2, activation_score=0.88, activated_by='seed'),
        ],
        nodes=[node1, node2],
    )


def _conclusion() -> CoreConclusion:
    return CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='이 두 갑옷에 대해 우선 검색부터 해줄래?',
        inferred_intent='open_information_request',
        activated_concepts=[1, 2],
        key_relations=[],
        explanation_summary='질문에 바로 답하기 전에 현재 주제의 외부 근거를 확인할 필요가 있다.',
    )


def test_search_need_evaluator_uses_graph_state() -> None:
    decision = SearchNeedEvaluator().evaluate(
        message='이 두 갑옷에 대해 우선 검색부터 해줄래?',
        thought_view=_thought_view(),
        conclusion=_conclusion(),
    )
    assert decision.need_search is True
    assert '찰갑' in decision.target_terms
    assert '체인메일' in decision.target_terms
    assert decision.reason == 'graph_too_sparse_for_answer'


def test_search_need_evaluator_triggers_on_statement_style_comparison_request() -> None:
    node1 = Node(id=11, raw_value='찰갑옷과', normalized_value='찰갑옷', node_kind='concept')
    node2 = Node(id=12, raw_value='미늘갑옷', normalized_value='미늘갑옷', node_kind='concept')
    node3 = Node(id=13, raw_value='사슬갑옷에', normalized_value='사슬갑옷', node_kind='concept')
    thought_view = ThoughtView(
        session_id='s2',
        message_text='찰갑옷과 미늘갑옷, 그리고 사슬갑옷에 대해서 차이점 중심으로 정리 부탁할게.',
        seed_nodes=[
            ActivatedNode(node=node1, activation_score=0.92, activated_by='seed'),
            ActivatedNode(node=node2, activation_score=0.90, activated_by='seed'),
            ActivatedNode(node=node3, activation_score=0.89, activated_by='seed'),
        ],
        nodes=[node1, node2, node3],
    )
    conclusion = CoreConclusion(
        session_id='s2',
        message_id=2,
        user_input_summary='찰갑옷과 미늘갑옷, 그리고 사슬갑옷에 대해서 차이점 중심으로 정리 부탁할게.',
        inferred_intent='graph_grounded_reasoning',
        activated_concepts=[11, 12, 13],
        key_relations=[21, 22],
        explanation_summary='질문의 핵심 차이, 사실, 이유 같은 내용을 바로 설명한다.',
    )
    decision = SearchNeedEvaluator().evaluate(
        message='찰갑옷과 미늘갑옷, 그리고 사슬갑옷에 대해서 차이점 중심으로 정리 부탁할게.',
        thought_view=thought_view,
        conclusion=conclusion,
    )
    assert decision.need_search is True
    assert decision.reason == 'graph_reasoning_needs_external_grounding'
    assert decision.target_terms[:3] == ['찰갑옷', '미늘갑옷', '사슬갑옷']


def test_search_need_evaluator_skips_when_search_grounding_already_present() -> None:
    search_node = Node(
        id=21,
        raw_value='체인메일',
        normalized_value='체인메일',
        node_kind='concept',
        payload={'source_counts': {'search': 1}, 'last_source_type': 'search'},
    )
    thought_view = ThoughtView(
        session_id='s3',
        message_text='체인메일이 뭐야?',
        seed_nodes=[ActivatedNode(node=search_node, activation_score=0.95, activated_by='seed')],
        nodes=[search_node],
    )
    conclusion = CoreConclusion(
        session_id='s3',
        message_id=3,
        user_input_summary='체인메일이 뭐야?',
        inferred_intent='graph_grounded_reasoning',
        activated_concepts=[21],
        key_relations=[301, 302],
        explanation_summary='질문의 핵심 차이, 사실, 이유 같은 내용을 바로 설명한다.',
    )
    decision = SearchNeedEvaluator().evaluate(
        message='체인메일이 뭐야?',
        thought_view=thought_view,
        conclusion=conclusion,
    )
    assert decision.need_search is False
    assert decision.reason == 'graph_sufficient_without_search'


def test_search_query_planner_receives_active_terms_and_returns_queries() -> None:
    client = FakeClient(json.dumps({
        'queries': ['찰갑 갑옷', '체인메일 갑옷'],
        'reason': '현재 활성 개념을 기준으로 갑옷 형식을 확인해야 함',
        'focus_terms': ['찰갑', '체인메일'],
    }))
    planner = SearchQueryPlanner(client=client)
    plan = planner.plan(
        model_name='gemma4:e2b',
        message='이 두 갑옷에 대해 우선 검색부터 해줄래?',
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        decision=SearchNeedEvaluator().evaluate(
            message='이 두 갑옷에 대해 우선 검색부터 해줄래?',
            thought_view=_thought_view(),
            conclusion=_conclusion(),
        ),
    )
    assert plan.queries == ['찰갑 갑옷', '체인메일 갑옷']
    assert client.last_format == 'json'
    prompt = client.last_messages[1]['content']
    assert '찰갑' in prompt
    assert '체인메일' in prompt


def test_search_sidecar_runs_planner_then_backend() -> None:
    client = FakeClient(json.dumps({
        'queries': ['찰갑 갑옷', '체인메일 갑옷'],
        'reason': '갑옷 종류 확인',
        'focus_terms': ['찰갑', '체인메일'],
    }))
    sidecar = SearchSidecar(query_planner=SearchQueryPlanner(client=client), backend=FakeBackend())
    result = sidecar.run(
        message='이 두 갑옷에 대해 우선 검색부터 해줄래?',
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        model_name='gemma4:e2b',
    )
    assert result.attempted is True
    assert result.plan is not None
    assert result.plan.queries == ['찰갑 갑옷', '체인메일 갑옷']
    assert result.results
    assert result.results[0].metadata['planned_query'] == '찰갑 갑옷'
