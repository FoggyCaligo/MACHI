from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.thinking.thought_engine import ThoughtEngine, ThoughtRequest
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def build_uow_factory(db_path: Path, schema_path: Path):
    def factory():
        return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True)
    return factory


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'memory.db'
        schema_path = Path(__file__).resolve().parents[2] / 'storage' / 'schema.sql'
        uow_factory = build_uow_factory(db_path, schema_path)

        ingest = GraphIngestService(uow_factory)
        activation = ActivationEngine(uow_factory)
        thinker = ThoughtEngine(uow_factory)

        ingest_result = ingest.ingest(
            GraphIngestRequest(
                session_id='session-thinking',
                turn_index=1,
                role='user',
                content='MK5에서는 profile과 project를 chat으로 통합하자. graph 구조가 더 맞다.',
            )
        )

        with uow_factory() as uow:
            edges = list(uow.edges.list_revision_candidates(min_contradiction_pressure=0.0, limit=50))
            assert len(edges) == 0
            local_edges = list(uow.edges.list_edges_for_nodes([1, 2, 3, 4, 5, 6], active_only=True))
            assert local_edges, 'ingest should create at least one co_occurs_with edge'
            edge = local_edges[0]
            uow.edges.bump_conflict(edge.id or 0, delta=3, pressure_delta=3.2, trust_delta=-0.18)
            uow.commit()

        thought_view = activation.build_view(
            ActivationRequest(
                session_id='session-thinking',
                content='MK5는 chat 통합 구조가 더 맞다.',
            )
        )
        result = thinker.think(
            ThoughtRequest(
                session_id='session-thinking',
                message_id=ingest_result.message_id,
                message_text='MK5는 chat 통합 구조가 더 맞다.',
            ),
            thought_view,
        )

        assert result.contradiction_signals, 'thinking should detect at least one contradiction signal'
        assert result.trust_updates, 'thinking should create trust updates'
        assert result.revision_actions, 'thinking should create revision actions'
        assert result.core_conclusion is not None, 'thinking should produce core conclusion'
        assert result.core_conclusion.activated_concepts, 'core conclusion should reference activated node ids'
        assert result.core_conclusion.key_relations, 'core conclusion should reference key edge ids'

        with uow_factory() as uow:
            revised = [edge for edge in uow.edges.list_edges_for_nodes([1, 2, 3, 4, 5, 6], active_only=False)]
            assert any(not edge.is_active for edge in revised), 'at least one edge should be deactivated after revision'
            recent_events = list(uow.graph_events.list_recent(limit=20))
            event_types = {event.event_type for event in recent_events}
            assert 'edge_conflict_registered' in event_types
            assert 'edge_deactivated_for_revision' in event_types

        print('PASS: thinking revision pipeline')


if __name__ == '__main__':
    main()
