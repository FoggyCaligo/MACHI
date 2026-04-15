from __future__ import annotations

import json

from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ActivatedNode, ThoughtView
from core.search.question_slot_planner import QuestionSlotPlanner
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
    node1 = Node(id=1, raw_value='판금갑옷', normalized_value='판금갑옷', node_kind='concept')
    node2 = Node(id=2, raw_value='찰갑', normalized_value='찰갑', node_kind='concept')
    node3 = Node(id=3, raw_value='사슬갑옷', normalized_value='사슬갑옷', node_kind='concept')
    node4 = Node(id=4, raw_value='미늘갑옷', normalized_value='미늘갑옷', node_kind='concept')
    return ThoughtView(
        session_id='s1',
        message_text='판금갑옷과 찰갑, 사슬갑옷, 미늘갑옷의 구조적 차이점과 방어력, 기동성에 대해 알려줘.',
        seed_nodes=[
            ActivatedNode(node=node1, activation_score=0.9, activated_by='seed'),
            ActivatedNode(node=node2, activation_score=0.88, activated_by='seed'),
            ActivatedNode(node=node3, activation_score=0.87, activated_by='seed'),
            ActivatedNode(node=node4, activation_score=0.86, activated_by='seed'),
        ],
        nodes=[node1, node2, node3, node4],
    )


def _conclusion() -> CoreConclusion:
    return CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='판금갑옷과 찰갑, 사슬갑옷, 미늘갑옷의 구조적 차이점과 방어력, 기동성에 대해 알려줘.',
        inferred_intent='graph_grounded_reasoning',
        activated_concepts=[1, 2, 3, 4],
        key_relations=[1, 2],
        explanation_summary='비교 대상은 여러 개지만 외부 근거 연결은 아직 충분하지 않다.',
    )


def test_question_slot_planner_extracts_entities_and_aspects() -> None:
    client = FakeClient(json.dumps({
        'entities': ['판금갑옷', '찰갑', '사슬갑옷', '미늘갑옷'],
        'aspects': ['구조', '방어력', '기동성'],
        'reason': '비교 대상과 비교 축을 슬롯으로 분리한다.',
    }))
    planner = QuestionSlotPlanner(client=client)
    plan = planner.plan(
        model_name='gemma3:4b',
        message=_conclusion().user_input_summary,
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        target_terms=['판금갑옷', '찰갑', '사슬갑옷', '미늘갑옷'],
    )
    assert plan.entities[:2] == ['판금갑옷', '찰갑']
    assert '구조' in plan.aspects
    assert any(slot.label == '판금갑옷:구조' for slot in plan.requested_slots)
    assert client.last_format == 'json'


def test_search_need_evaluator_uses_missing_slots_not_graph_size_only() -> None:
    slot_client = FakeClient(json.dumps({
        'entities': ['판금갑옷', '찰갑', '사슬갑옷', '미늘갑옷'],
        'aspects': ['구조', '방어력', '기동성'],
        'reason': '비교 대상과 비교 축을 슬롯으로 분리한다.',
    }))
    slot_plan = QuestionSlotPlanner(client=slot_client).plan(
        model_name='gemma3:4b',
        message=_conclusion().user_input_summary,
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        target_terms=['판금갑옷', '찰갑', '사슬갑옷', '미늘갑옷'],
    )
    decision = SearchNeedEvaluator().evaluate(
        message=_conclusion().user_input_summary,
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        slot_plan=slot_plan,
    )
    assert decision.need_search is True
    assert decision.reason == 'missing_slot_grounding'
    assert decision.missing_slots


def test_search_sidecar_runs_missing_slot_queries() -> None:
    slot_client = FakeClient(json.dumps({
        'entities': ['판금갑옷', '찰갑', '사슬갑옷', '미늘갑옷'],
        'aspects': ['구조', '방어력', '기동성'],
        'reason': '비교 대상과 비교 축을 슬롯으로 분리한다.',
    }))
    sidecar = SearchSidecar(slot_planner=QuestionSlotPlanner(client=slot_client), query_planner=SearchQueryPlanner(), backend=FakeBackend())
    result = sidecar.run(
        message=_conclusion().user_input_summary,
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        model_name='gemma3:4b',
    )
    assert result.attempted is True
    assert result.planning_attempted is True
    assert result.slot_plan is not None
    assert result.plan is not None
    assert result.plan.queries
    assert result.results


def test_search_sidecar_fails_open_when_slot_planner_returns_invalid_json() -> None:
    slot_client = FakeClient('not-json-at-all')
    sidecar = SearchSidecar(slot_planner=QuestionSlotPlanner(client=slot_client), query_planner=SearchQueryPlanner(), backend=FakeBackend())
    result = sidecar.run(
        message=_conclusion().user_input_summary,
        thought_view=_thought_view(),
        conclusion=_conclusion(),
        model_name='gemma3:4b',
    )
    assert result.attempted is False
    assert result.planning_attempted is True
    assert result.decision.need_search is True
    assert result.decision.reason == 'slot_planner_failed_needs_grounding'
    assert result.error == 'question slot planner returned invalid JSON'
