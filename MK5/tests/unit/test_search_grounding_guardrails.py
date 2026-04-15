from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline
from core.entities.conclusion import CoreConclusion
from core.search.question_slot_planner import QuestionSlotPlanner
from core.search.search_need_evaluator import SearchNeedDecision
from core.search.search_query_planner import SearchPlan, SearchQueryPlanner
from core.search.search_sidecar import SearchRunResult
from core.verbalization.action_layer_builder import ActionLayerBuilder


class FakeChatResult:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, *, model_name, messages, stream=False, options=None, response_format=None):
        return FakeChatResult(self.content)


def test_question_slot_planner_supports_structured_search_aspects() -> None:
    planner = QuestionSlotPlanner(
        client=FakeClient(
            json.dumps(
                {
                    'entities': ['가죽갑옷', '누비갑옷'],
                    'search_aspects': ['구조'],
                    'comparison_axes': ['차이점'],
                    'reason': '검색으로 확인할 구조 축과 최종 비교축을 분리했다.',
                }
            )
        )
    )

    plan = planner.plan(
        model_name='gemma3:4b',
        message='가죽갑옷과 누비갑옷의 차이점에 대해 알려줘.',
        thought_view=type('ThoughtViewStub', (), {'seed_nodes': [], 'nodes': []})(),
        conclusion=CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='armor comparison',
            inferred_intent='structure_review',
        ),
        target_terms=['가죽갑옷', '누비갑옷'],
    )

    assert plan.entities == ['가죽갑옷', '누비갑옷']
    assert plan.aspects == ['구조']
    assert plan.comparison_axes == ['차이점']
    assert [slot.label for slot in plan.requested_slots] == [
        '가죽갑옷',
        '가죽갑옷:구조',
        '누비갑옷',
        '누비갑옷:구조',
    ]


def test_search_query_planner_uses_structured_missing_slots_without_string_filters() -> None:
    planner = SearchQueryPlanner()
    decision = SearchNeedDecision(
        need_search=True,
        reason='missing_slot_grounding',
        gap_summary='missing grounding',
        missing_slots=[
            {'kind': 'entity', 'entity': '가죽갑옷', 'aspect': '', 'label': '가죽갑옷'},
            {'kind': 'aspect', 'entity': '가죽갑옷', 'aspect': '구조', 'label': '가죽갑옷:구조'},
            {'kind': 'entity', 'entity': '누비갑옷', 'aspect': '', 'label': '누비갑옷'},
            {'kind': 'aspect', 'entity': '누비갑옷', 'aspect': '구조', 'label': '누비갑옷:구조'},
        ],
    )

    plan = planner.plan(
        model_name='gemma3:4b',
        message='가죽갑옷과 누비갑옷의 차이점에 대해 알려줘.',
        thought_view=type('ThoughtViewStub', (), {})(),
        conclusion=CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='armor comparison',
            inferred_intent='structure_review',
        ),
        decision=decision,
    )

    assert plan.queries == ['가죽갑옷 구조', '누비갑옷 구조']


def test_chat_pipeline_marks_no_evidence_without_string_matching(tmp_path: Path) -> None:
    pipeline = ChatPipeline(db_path=tmp_path / 'memory.db', schema_path=ROOT / 'storage' / 'schema.sql')
    conclusion = CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='armor comparison',
        inferred_intent='structure_review',
    )
    search_run = SearchRunResult(
        attempted=True,
        planning_attempted=True,
        decision=SearchNeedDecision(
            need_search=True,
            reason='missing_slot_grounding',
            gap_summary='missing grounding',
            requested_slots=[
                {'kind': 'entity', 'entity': '가죽갑옷', 'aspect': '', 'label': '가죽갑옷'},
                {'kind': 'aspect', 'entity': '가죽갑옷', 'aspect': '구조', 'label': '가죽갑옷:구조'},
                {'kind': 'entity', 'entity': '누비갑옷', 'aspect': '', 'label': '누비갑옷'},
                {'kind': 'aspect', 'entity': '누비갑옷', 'aspect': '구조', 'label': '누비갑옷:구조'},
            ],
            missing_slots=[
                {'kind': 'entity', 'entity': '가죽갑옷', 'aspect': '', 'label': '가죽갑옷'},
                {'kind': 'aspect', 'entity': '가죽갑옷', 'aspect': '구조', 'label': '가죽갑옷:구조'},
                {'kind': 'entity', 'entity': '누비갑옷', 'aspect': '', 'label': '누비갑옷'},
                {'kind': 'aspect', 'entity': '누비갑옷', 'aspect': '구조', 'label': '누비갑옷:구조'},
            ],
        ),
        plan=SearchPlan(
            queries=['가죽갑옷 구조', '누비갑옷 구조'],
            reason='test plan',
            focus_terms=['가죽갑옷', '누비갑옷'],
        ),
        results=[],
    )

    pipeline._attach_search_context(conclusion, search_run=search_run)
    search_context = conclusion.metadata['search_context']

    assert search_context['need_search'] is True
    assert search_context['grounded_terms'] == []
    assert search_context['missing_terms'] == ['가죽갑옷', '누비갑옷']
    assert search_context['missing_aspects'] == ['구조']
    assert search_context['no_evidence_found'] is True


def test_action_layer_builder_becomes_conservative_when_no_evidence_is_reported() -> None:
    conclusion = CoreConclusion(
        session_id='s1',
        message_id=1,
        user_input_summary='armor comparison',
        inferred_intent='structure_review',
    )
    conclusion.metadata['search_context'] = {
        'need_search': True,
        'attempted': True,
        'result_count': 0,
        'missing_terms': ['가죽갑옷', '누비갑옷'],
        'missing_aspects': ['구조'],
        'no_evidence_found': True,
    }

    action = ActionLayerBuilder().build(conclusion)

    assert action.metadata['search_attempted'] is True
    assert action.metadata['search_required'] is True
    assert action.metadata['search_result_count'] == 0
    assert action.metadata['no_evidence_found'] is True
    assert action.metadata['missing_aspect_count'] == 1
    assert any('구조' in item for item in action.do_not_claim)
