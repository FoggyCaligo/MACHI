from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest, UserFacingChatError
from core.entities.conclusion import CoreConclusion
from core.search.search_need_evaluator import SearchNeedDecision
from core.search.search_sidecar import SearchRunResult, SearchSidecar
from core.verbalization.verbalizer import VerbalizationResult, Verbalizer


class FakeVerbalizer(Verbalizer):
    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = 'mk5-graph-core') -> VerbalizationResult:
        raise AssertionError('verbalize() should not be reached when search model selection is required')


class SearchModelSelectionRequiredSidecar(SearchSidecar):
    def run(self, *, message: str, thought_view, conclusion: CoreConclusion, model_name: str) -> SearchRunResult:
        return SearchRunResult(
            attempted=False,
            planning_attempted=True,
            decision=SearchNeedDecision(
                need_search=True,
                reason='slot_planner_failed_needs_grounding',
                gap_summary='search requires explicit grounding',
                target_terms=['판금갑옷', '찰갑', '사슬갑옷'],
            ),
            error='question slot planner requires a selectable LLM model',
        )


def test_chat_pipeline_raises_user_facing_error_when_search_model_is_not_selected(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    pipeline = ChatPipeline(
        db_path=db_path,
        schema_path=schema_path,
        verbalizer=FakeVerbalizer(),
        search_sidecar=SearchModelSelectionRequiredSidecar(),
    )

    with pytest.raises(UserFacingChatError) as exc_info:
        pipeline.process(
            ChatPipelineRequest(
                session_id='session-search-error',
                message='판금갑옷과 찰갑, 사슬갑옷, 미늘갑옷, 가죽갑옷의 구조적 차이점과 방어력, 기동성에 대해 알려줘.',
                turn_index=1,
                model_name='mk5-graph-core',
            )
        )

    message = str(exc_info.value)
    assert '외부 검색이 필요' in message
    assert '모델' in message
