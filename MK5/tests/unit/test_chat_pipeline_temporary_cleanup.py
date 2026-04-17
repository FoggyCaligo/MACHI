from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest
from core.entities.conclusion import CoreConclusion, DerivedActionLayer, ThoughtResult
from core.entities.thought_view import ThoughtView
from core.search.search_need_evaluator import SearchNeedDecision
from core.search.search_sidecar import SearchRunResult
from core.update.temporary_edge_service import TemporaryEdgeCleanupResult
from core.verbalization.verbalizer import VerbalizationResult, Verbalizer


class StubActivationEngine:
    def __init__(self) -> None:
        self.calls = 0

    def build_view(self, request) -> ThoughtView:
        self.calls += 1
        return ThoughtView(session_id=request.session_id, message_text=request.content, metadata={})


class StubThoughtEngine:
    def __init__(self) -> None:
        self.calls = 0

    def think(self, request, thought_view: ThoughtView) -> ThoughtResult:
        self.calls += 1
        conclusion = CoreConclusion(
            session_id=request.session_id,
            message_id=request.message_id,
            user_input_summary=request.message_text,
            inferred_intent='open_information_request',
            explanation_summary=f'pass-{self.calls}',
            metadata={},
        )
        return ThoughtResult(
            session_id=request.session_id,
            message_id=request.message_id,
            core_conclusion=conclusion,
            metadata={
                'intent_snapshot': {
                    'snapshot_intent': 'open_information_request',
                    'topic_continuity': 'shifted_topic',
                    'topic_overlap_count': 0,
                    'shifted': True,
                    'tone_hint': 'natural_concise_korean',
                }
            },
        )


class StubTemporaryEdgeService:
    def cleanup_on_topic_shift(self, *args, **kwargs) -> TemporaryEdgeCleanupResult:
        return TemporaryEdgeCleanupResult(
            attempted=True,
            triggered=True,
            topic_continuity='shifted_topic',
            topic_overlap_count=0,
            deactivated_edge_ids=[101],
            reason='shift_cleanup_executed',
        )


class StubSearchSidecar:
    def run(self, *, message: str, thought_view: ThoughtView, conclusion: CoreConclusion, model_name: str) -> SearchRunResult:
        return SearchRunResult(
            attempted=False,
            decision=SearchNeedDecision(
                need_search=False,
                reason='enough_context',
                gap_summary='',
            ),
            results=[],
            error=None,
        )


class StubVerbalizer(Verbalizer):
    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = 'mk5-graph-core') -> VerbalizationResult:
        return VerbalizationResult(
            user_response=f"summary:{conclusion.explanation_summary}",
            internal_explanation='stub',
            derived_action=DerivedActionLayer(
                response_mode='direct_answer_with_uncertainty',
                answer_goal='answer directly',
            ),
            used_llm=False,
        )


def test_chat_pipeline_rebuilds_thought_after_temporary_cleanup(tmp_path: Path) -> None:
    pipeline = ChatPipeline(
        db_path=tmp_path / 'memory.db',
        schema_path=ROOT / 'storage' / 'schema.sql',
        verbalizer=StubVerbalizer(),
        search_sidecar=StubSearchSidecar(),
    )
    pipeline.activation_engine = StubActivationEngine()
    pipeline.thought_engine = StubThoughtEngine()
    pipeline.temporary_edge_service = StubTemporaryEdgeService()

    result = pipeline.process(
        ChatPipelineRequest(
            session_id='temp-cleanup-session',
            message='인칭이 왜 헷갈리지?',
            turn_index=1,
            model_name='gemma3:4b',
        )
    )

    assert pipeline.activation_engine.calls == 2
    assert pipeline.thought_engine.calls == 2
    assert result['reply'] == 'summary:pass-2'
    assert result['debug']['temporary_edge_cleanup']['triggered'] is True
    assert result['debug']['temporary_edge_cleanup']['deactivated_count'] == 1
