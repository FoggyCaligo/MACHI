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
from core.search.search_coverage_refiner import SearchCoverageRefiner
from core.search.search_need_evaluator import SearchNeedDecision
from core.search.search_query_planner import SearchPlan, SearchQueryPlanner
from core.search.search_sidecar import (
    CompositeSearchBackend,
    SearchBackendResult,
    SearchEvidence,
    SearchRunResult,
)
from core.verbalization.action_layer_builder import ActionLayerBuilder


class FakeChatResult:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, *, model_name, messages, stream=False, options=None, response_format=None):
        return FakeChatResult(self.content)


class StaticBackend:
    def __init__(self, results: list[SearchEvidence], *, provider_errors: list[dict[str, str]] | None = None) -> None:
        self.results = results
        self.provider_errors = provider_errors or []

    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> SearchBackendResult:
        return SearchBackendResult(
            results=self.results[:max_results],
            provider_errors=list(self.provider_errors),
        )


def test_question_slot_planner_supports_structured_search_aspects() -> None:
    planner = QuestionSlotPlanner(
        client=FakeClient(
            json.dumps(
                {
                    'entities': ['plate armor', 'mail armor'],
                    'search_aspects': ['construction'],
                    'comparison_axes': ['mobility'],
                    'reason': 'Split factual lookup axes from final comparison axes.',
                }
            )
        )
    )

    plan = planner.plan(
        model_name='gemma3:4b',
        message='Compare plate armor and mail armor.',
        thought_view=type('ThoughtViewStub', (), {'seed_nodes': [], 'nodes': []})(),
        conclusion=CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='armor comparison',
            inferred_intent='structure_review',
        ),
        target_terms=['plate armor', 'mail armor'],
    )

    assert plan.entities == ['plate armor', 'mail armor']
    assert plan.aspects == ['construction']
    assert plan.comparison_axes == ['mobility']
    assert [slot.label for slot in plan.requested_slots] == [
        'plate armor',
        'plate armor:construction',
        'mail armor',
        'mail armor:construction',
    ]


def test_search_coverage_refiner_marks_aspects_from_evidence_summaries() -> None:
    refiner = SearchCoverageRefiner(
        client=FakeClient(
            json.dumps(
                {
                    'covered_slot_labels': ['plate armor', 'plate armor:construction'],
                    'missing_slot_labels': ['mail armor', 'mail armor:construction'],
                    'reason': 'Only plate armor evidence includes a construction summary.',
                }
            )
        )
    )
    slot_plan = QuestionSlotPlanner(
        client=FakeClient(
            json.dumps(
                {
                    'entities': ['plate armor', 'mail armor'],
                    'search_aspects': ['construction'],
                    'comparison_axes': ['mobility'],
                    'reason': 'Split factual lookup axes from final comparison axes.',
                }
            )
        )
    ).plan(
        model_name='gemma3:4b',
        message='Compare plate armor and mail armor.',
        thought_view=type('ThoughtViewStub', (), {'seed_nodes': [], 'nodes': []})(),
        conclusion=CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='armor comparison',
            inferred_intent='structure_review',
        ),
        target_terms=['plate armor', 'mail armor'],
    )

    analysis = refiner.refine(
        model_name='gemma3:4b',
        message='Compare plate armor and mail armor.',
        conclusion=CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='armor comparison',
            inferred_intent='structure_review',
        ),
        slot_plan=slot_plan,
        evidences=[
            SearchEvidence(
                title='Plate armor',
                snippet='Plate armor uses large rigid plates.',
                url='https://example.test/plate',
                provider='provider-a',
            )
        ],
    )

    assert analysis.covered_slot_labels == ['plate armor', 'plate armor:construction']
    assert analysis.missing_slot_labels == ['mail armor', 'mail armor:construction']


def test_search_query_planner_uses_structured_missing_slots() -> None:
    planner = SearchQueryPlanner()
    decision = SearchNeedDecision(
        need_search=True,
        reason='missing_slot_grounding',
        gap_summary='missing grounding',
        missing_slots=[
            {'kind': 'entity', 'entity': 'plate armor', 'aspect': '', 'label': 'plate armor'},
            {'kind': 'aspect', 'entity': 'plate armor', 'aspect': 'construction', 'label': 'plate armor:construction'},
            {'kind': 'entity', 'entity': 'mail armor', 'aspect': '', 'label': 'mail armor'},
            {'kind': 'aspect', 'entity': 'mail armor', 'aspect': 'construction', 'label': 'mail armor:construction'},
        ],
    )

    plan = planner.plan(
        model_name='gemma3:4b',
        message='Compare plate armor and mail armor.',
        thought_view=type('ThoughtViewStub', (), {})(),
        conclusion=CoreConclusion(
            session_id='s1',
            message_id=1,
            user_input_summary='armor comparison',
            inferred_intent='structure_review',
        ),
        decision=decision,
    )

    assert plan.queries == ['plate armor', 'mail armor']
    assert plan.metadata['planned_aspect_extraction'] == [
        {'entity': 'plate armor', 'aspects': ['construction']},
        {'entity': 'mail armor', 'aspects': ['construction']},
    ]


def test_chat_pipeline_marks_no_evidence_when_search_returns_no_results(tmp_path: Path) -> None:
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
                {'kind': 'entity', 'entity': 'plate armor', 'aspect': '', 'label': 'plate armor'},
                {'kind': 'aspect', 'entity': 'plate armor', 'aspect': 'construction', 'label': 'plate armor:construction'},
                {'kind': 'entity', 'entity': 'mail armor', 'aspect': '', 'label': 'mail armor'},
                {'kind': 'aspect', 'entity': 'mail armor', 'aspect': 'construction', 'label': 'mail armor:construction'},
            ],
            missing_slots=[
                {'kind': 'entity', 'entity': 'plate armor', 'aspect': '', 'label': 'plate armor'},
                {'kind': 'aspect', 'entity': 'plate armor', 'aspect': 'construction', 'label': 'plate armor:construction'},
                {'kind': 'entity', 'entity': 'mail armor', 'aspect': '', 'label': 'mail armor'},
                {'kind': 'aspect', 'entity': 'mail armor', 'aspect': 'construction', 'label': 'mail armor:construction'},
            ],
        ),
        plan=SearchPlan(
            queries=['plate armor', 'mail armor'],
            reason='test plan',
            focus_terms=['plate armor', 'mail armor'],
        ),
        results=[],
    )

    pipeline._attach_search_context(conclusion, search_run=search_run)
    search_context = conclusion.metadata['search_context']

    assert search_context['need_search'] is True
    assert search_context['grounded_terms'] == []
    assert search_context['missing_terms'] == ['plate armor', 'mail armor']
    assert search_context['missing_aspects'] == ['construction']
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
        'missing_terms': ['plate armor', 'mail armor'],
        'missing_aspects': ['construction'],
        'no_evidence_found': True,
    }

    action = ActionLayerBuilder().build(conclusion)

    assert action.metadata['search_attempted'] is True
    assert action.metadata['search_required'] is True
    assert action.metadata['search_result_count'] == 0
    assert action.metadata['no_evidence_found'] is True
    assert action.metadata['missing_aspect_count'] == 1
    assert any('construction' in item for item in action.do_not_claim)


def test_composite_search_backend_merges_results_and_provider_errors() -> None:
    backend = CompositeSearchBackend(
        backends=[
            StaticBackend(
                [
                    SearchEvidence(
                        title='Plate armor',
                        snippet='Rigid metal plates.',
                        url='https://example.test/plate',
                        provider='provider-a',
                    )
                ],
                provider_errors=[{'provider': 'provider-a', 'query': 'armor', 'error': 'partial'}],
            ),
            StaticBackend(
                [
                    SearchEvidence(
                        title='Mail armor',
                        snippet='Interlinked rings.',
                        url='https://example.test/mail',
                        provider='provider-b',
                    )
                ]
            ),
        ]
    )

    result = backend.search('armor', max_results=4, timeout_seconds=1.0)

    assert [item.title for item in result.results] == ['Plate armor', 'Mail armor']
    assert result.provider_errors == [{'provider': 'provider-a', 'query': 'armor', 'error': 'partial'}]
