from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest
from core.entities.conclusion import DerivedActionLayer
from core.search.search_need_evaluator import SearchNeedDecision
from core.search.search_sidecar import SearchRunResult, SearchSidecar
from core.update.connect_type_promotion_service import ConnectTypePromotionService
from core.update.model_edge_assertion_service import ModelEdgeAssertionService
from core.entities.conclusion_view import ConclusionView
from core.verbalization.verbalizer import VerbalizationResult, Verbalizer
from storage.sqlite.unit_of_work import SqliteUnitOfWork


class FakeVerbalizer(Verbalizer):
    def verbalize(self, conclusion: ConclusionView, *, model_name: str = 'mk5-graph-core') -> VerbalizationResult:
        return VerbalizationResult(
            user_response='ok',
            internal_explanation='ok',
            derived_action=DerivedActionLayer(response_mode='test', answer_goal='test'),
            used_llm=False,
            llm_error=None,
        )


class NoSearchSidecar(SearchSidecar):
    def run(self, *, message: str, thought_view, conclusion, model_name: str) -> SearchRunResult:
        return SearchRunResult(
            attempted=False,
            planning_attempted=False,
            decision=SearchNeedDecision(need_search=False, reason='test_no_search', gap_summary=''),
            results=[],
            provider_errors=[],
        )



class AssertionClientPlain:
    def chat(self, **kwargs):  # noqa: ANN003
        return SimpleNamespace(
            content='{"new_edges":[{"from_node_id":1,"to_node_id":2,"edge_family":"concept","connect_type":"reflective","relation_detail":{}}]}'
        )


class AssertionClientWeighted:
    def chat(self, **kwargs):  # noqa: ANN003
        return SimpleNamespace(
            content='{"new_edges":[{"from_node_id":1,"to_node_id":2,"edge_family":"concept","connect_type":"reflective","relation_detail":{"source_type":"search","claim_domain":"world_fact"}}]}'
        )


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)

    return factory


def build_pipeline(tmp_path: Path, *, assertion_client, threshold: int) -> ChatPipeline:
    db_path = tmp_path / 'memory.db'
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = ROOT / 'storage' / 'schema.sql'
    uow_factory = build_uow_factory(db_path, schema_path)
    assertion_service = ModelEdgeAssertionService(uow_factory=uow_factory, client=assertion_client)
    return ChatPipeline(
        db_path=db_path,
        schema_path=schema_path,
        verbalizer=FakeVerbalizer(),
        search_sidecar=NoSearchSidecar(),
        model_edge_assertion_service=assertion_service,
        connect_type_promotion_service=ConnectTypePromotionService(threshold=threshold, max_scan=200),
    )


def run_turns(pipeline: ChatPipeline, *, turns: int) -> dict:
    response = {}
    for turn in range(1, turns + 1):
        response = pipeline.process(
            ChatPipelineRequest(
                session_id='session-promo-e2e',
                message='A와 B는 같은 이름 변형일 수 있어.',
                turn_index=turn,
                model_name='gemma3:4b',
            )
        )
    return response


def test_connect_type_promotion_occurs_in_chat_pipeline(tmp_path: Path) -> None:
    pipeline = build_pipeline(tmp_path, assertion_client=AssertionClientWeighted(), threshold=3)
    response = run_turns(pipeline, turns=3)

    debug = response['debug']
    assert 'model_edge_assertion' in debug
    assert 'connect_type_promotion' in debug
    assert debug['connect_type_promotion']['attempted'] is True
    assert debug['connect_type_promotion']['promotion_count'] >= 1


def test_connect_type_promotion_does_not_trigger_under_high_threshold(tmp_path: Path) -> None:
    pipeline = build_pipeline(tmp_path, assertion_client=AssertionClientPlain(), threshold=5)
    response = run_turns(pipeline, turns=3)

    debug = response['debug']
    assert debug['connect_type_promotion']['attempted'] is True
    assert debug['connect_type_promotion']['promotion_count'] == 0


def test_connect_type_promotion_triggers_after_repetition_crosses_threshold(tmp_path: Path) -> None:
    before_pipeline = build_pipeline(tmp_path / 'repeat_before', assertion_client=AssertionClientPlain(), threshold=5)
    before = run_turns(before_pipeline, turns=4)
    assert before['debug']['connect_type_promotion']['promotion_count'] == 0

    after_pipeline = build_pipeline(tmp_path / 'repeat_after', assertion_client=AssertionClientPlain(), threshold=5)
    after = run_turns(after_pipeline, turns=5)
    assert after['debug']['connect_type_promotion']['promotion_count'] >= 1
