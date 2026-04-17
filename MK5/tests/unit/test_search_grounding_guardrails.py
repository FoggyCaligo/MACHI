from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.entities.conclusion import CoreConclusion
from core.search.search_need_evaluator import SearchNeedEvaluator
from core.search.search_query_planner import SearchQueryPlanner
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def _uow_factory(tmp_path, schema_path):
    def factory():
        return SqliteUnitOfWork(tmp_path / 'memory.db', schema_path=schema_path, initialize_schema=True)
    return factory


def test_current_turn_nodes_do_not_count_as_grounding(tmp_path):
    schema_path = 'storage/schema.sql'
    uow_factory = _uow_factory(tmp_path, schema_path)
    ingest = GraphIngestService(uow_factory)
    result = ingest.ingest(GraphIngestRequest(session_id='s1', turn_index=1, role='user', content='단테의 신곡 알려줘', source_type='user', claim_domain='self_report'))
    engine = ActivationEngine(uow_factory)
    thought_view = engine.build_view(ActivationRequest(session_id='s1', content='단테의 신곡 알려줘', current_root_event_id=result.root_event_id))
    conclusion = CoreConclusion(session_id='s1', message_id=result.message_id, user_input_summary='단테의 신곡 알려줘', inferred_intent='informational', explanation_summary='x')

    evaluator = SearchNeedEvaluator()
    decision = evaluator.evaluate(message='단테의 신곡 알려줘', thought_view=thought_view, conclusion=conclusion)
    assert decision.need_search is True
    assert '단테' in decision.metadata['missing_terms']


def test_query_planner_emits_individual_missing_concepts_only():
    planner = SearchQueryPlanner()
    decision = SearchNeedEvaluator().evaluate(message='단테의 신곡 알려줘', thought_view=type('TV', (), {'seed_blocks': [], 'nodes': [], 'seed_nodes': [], 'metadata': {}})(), conclusion=CoreConclusion(session_id='s1', message_id=None, user_input_summary='', inferred_intent='informational', explanation_summary=''))
    # fallback seed_blocks empty => no terms; inject missing_terms directly for planner check
    decision.metadata['missing_terms'] = ['단테', '신곡']
    plan = planner.plan(message='단테의 신곡 알려줘', thought_view=None, conclusion=None, decision=decision)
    assert plan.queries == ['단테', '신곡']
