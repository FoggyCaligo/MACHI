from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest, UserFacingChatError
from core.entities.conclusion import CoreConclusion, DerivedActionLayer
from core.search.search_need_evaluator import SearchNeedDecision
from core.search.search_sidecar import SearchRunResult, SearchSidecar
from core.verbalization.verbalizer import VerbalizationResult, Verbalizer


class FakeVerbalizer(Verbalizer):
    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = 'mk5-graph-core') -> VerbalizationResult:
        raise AssertionError('verbalize() should not be reached when search model selection is required')


class TimeoutVerbalizer(Verbalizer):
    def verbalize(self, conclusion: CoreConclusion, *, model_name: str = 'mk5-graph-core') -> VerbalizationResult:
        return VerbalizationResult(
            user_response='',
            internal_explanation='timeout',
            derived_action=DerivedActionLayer(
                response_mode='direct_answer_with_uncertainty',
                answer_goal='report timeout',
            ),
            used_llm=False,
            llm_error='llm_verbalization_failed:timed out',
            llm_error_code='timeout',
        )


class SearchModelSelectionRequiredSidecar(SearchSidecar):
    def run(self, *, message: str, meaning_blocks, resolved_nodes, current_root_event_id: int | None, model_name: str) -> SearchRunResult:
        return SearchRunResult(
            attempted=False,
            planning_attempted=True,
            decision=SearchNeedDecision(
                need_search=True,
                reason='missing_usable_grounding',
                gap_summary='search requires explicit grounding',
                target_terms=['plate armor', 'lamellar', 'mail armor'],
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
                message='Compare plate armor, lamellar, mail armor, scale armor, and leather armor.',
                turn_index=1,
                model_name='mk5-graph-core',
            )
        )

    message = str(exc_info.value)
    assert '검색이 필요' in message or '모델' in message


def test_chat_pipeline_raises_user_facing_error_when_verbalizer_times_out(tmp_path: Path) -> None:
    db_path = tmp_path / 'memory.db'
    schema_path = ROOT / 'storage' / 'schema.sql'
    pipeline = ChatPipeline(
        db_path=db_path,
        schema_path=schema_path,
        verbalizer=TimeoutVerbalizer(),
        search_sidecar=SearchSidecar(),
    )

    with pytest.raises(UserFacingChatError) as exc_info:
        pipeline.process(
            ChatPipelineRequest(
                session_id='session-timeout',
                message='안녕하세요',
                turn_index=1,
                model_name='gemma3:4b',
            )
        )

    assert '제한 시간' in str(exc_info.value)
