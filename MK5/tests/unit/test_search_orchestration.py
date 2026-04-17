from core.activation.activation_engine import ActivationRequest, ActivationEngine
from core.entities.conclusion import CoreConclusion
from core.search.search_sidecar import SearchBackendResult, SearchEvidence, SearchSidecar
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


class FakeBackend:
    def __init__(self, mapping):
        self.mapping = mapping

    def search(self, query: str, *, max_results: int, timeout_seconds: float):
        return SearchBackendResult(results=list(self.mapping.get(query, [])))


def _uow_factory(tmp_path, schema_path):
    def factory():
        return SqliteUnitOfWork(tmp_path / 'memory.db', schema_path=schema_path, initialize_schema=True)
    return factory


def test_search_need_uses_missing_concepts_and_individual_queries(tmp_path):
    schema_path = 'storage/schema.sql'
    uow_factory = _uow_factory(tmp_path, schema_path)
    ingest = GraphIngestService(uow_factory)
    req = GraphIngestRequest(session_id='s1', turn_index=1, role='user', content='안녕? 단테의 신곡에 대해 알려줄래?', source_type='user', claim_domain='self_report')
    result = ingest.ingest(req)
    engine = ActivationEngine(uow_factory)
    thought_view = engine.build_view(ActivationRequest(session_id='s1', content=req.content, current_root_event_id=result.root_event_id))
    conclusion = CoreConclusion(session_id='s1', message_id=result.message_id, user_input_summary=req.content, inferred_intent='informational', explanation_summary='x')

    backend = FakeBackend({'단테': [SearchEvidence(title='단테', snippet='시인', url='https://ex/dante')], '신곡': [SearchEvidence(title='신곡', snippet='단테의 작품', url='https://ex/divine-comedy')]})
    sidecar = SearchSidecar(backend=backend)
    run = sidecar.run(message=req.content, thought_view=thought_view, conclusion=conclusion, model_name='mk5-graph-core')
    assert run.decision.need_search is True
    assert '단테' in run.decision.metadata['missing_terms']
    assert '신곡' in run.decision.metadata['missing_terms']
    assert run.plan is not None
    assert run.plan.queries == ['단테', '신곡']
    assert all(' ' not in q.strip() for q in run.plan.queries if q.strip())


def test_search_sidecar_skips_when_prior_search_grounding_exists(tmp_path):
    schema_path = 'storage/schema.sql'
    uow_factory = _uow_factory(tmp_path, schema_path)
    ingest = GraphIngestService(uow_factory)
    ingest.ingest(GraphIngestRequest(session_id='s1', turn_index=1, role='search', content='단테의 신곡: 단테 알리기에리의 서사시', source_type='search', claim_domain='world_fact'))
    result = ingest.ingest(GraphIngestRequest(session_id='s1', turn_index=2, role='user', content='단테의 신곡 알려줘', source_type='user', claim_domain='self_report'))
    engine = ActivationEngine(uow_factory)
    thought_view = engine.build_view(ActivationRequest(session_id='s1', content='단테의 신곡 알려줘', current_root_event_id=result.root_event_id))
    conclusion = CoreConclusion(session_id='s1', message_id=result.message_id, user_input_summary='단테의 신곡 알려줘', inferred_intent='informational', explanation_summary='x')

    sidecar = SearchSidecar(backend=FakeBackend({}))
    run = sidecar.run(message='단테의 신곡 알려줘', thought_view=thought_view, conclusion=conclusion, model_name='mk5-graph-core')
    assert run.decision.need_search is False
    assert run.attempted is False
