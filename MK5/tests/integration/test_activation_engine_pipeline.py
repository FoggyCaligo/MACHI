from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.activation.activation_engine import ActivationEngine, ActivationRequest
from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'memory.db'
        schema_path = ROOT / 'storage' / 'schema.sql'

        with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True):
            pass

        def make_uow() -> SqliteUnitOfWork:
            return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=False)

        ingest = GraphIngestService(make_uow)
        ingest.ingest(
            GraphIngestRequest(
                session_id='session-1',
                turn_index=1,
                role='user',
                content='MK5에서는 profile과 project와 chat을 분리하지 말자. chat으로 통합하는 게 더 맞아.',
            )
        )
        ingest.ingest(
            GraphIngestRequest(
                session_id='session-1',
                turn_index=2,
                role='user',
                content='MK5에서 chat 통합은 맞아. project와 profile 분리는 말고 chat으로 가자.',
            )
        )

        engine = ActivationEngine(make_uow)
        view = engine.build_view(
            ActivationRequest(
                session_id='session-1',
                content='MK5에서는 chat 통합이 맞고 profile과 project를 분리하지 말자.',
            )
        )

        assert view.seed_blocks, 'Activation should preserve segmented seed blocks'
        assert view.seed_nodes, 'Activation should resolve at least one durable seed node'
        assert view.nodes, 'Thought view should contain local nodes'
        assert view.edges, 'Thought view should collect neighbor edges around seeds'
        assert view.metadata['seed_node_count'] > 0
        normalized_values = {(node.normalized_value or '') for node in view.nodes}
        assert 'mk5' in normalized_values
        assert any(edge.connect_semantics == 'same_sentence_co_occurrence' for edge in view.edges)


if __name__ == '__main__':
    main()
