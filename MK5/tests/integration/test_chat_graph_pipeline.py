from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.update.graph_ingest_service import GraphIngestRequest, GraphIngestService
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "memory.db"
        schema_path = ROOT / "storage" / "schema.sql"

        with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True):
            pass

        def make_uow() -> SqliteUnitOfWork:
            return SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=False)

        service = GraphIngestService(make_uow)

        first = service.ingest(
            GraphIngestRequest(
                session_id="session-1",
                turn_index=1,
                role="user",
                content="MK5에서는 profile과 project와 chat을 분리하지 말자. chat으로 통합하는 게 더 맞아.",
            )
        )
        assert first.block_count > 0
        assert first.created_node_ids
        assert first.created_edge_ids

        second = service.ingest(
            GraphIngestRequest(
                session_id="session-1",
                turn_index=2,
                role="user",
                content="MK5에서 chat 통합은 맞아. profile과 project를 따로 두지 말자.",
            )
        )
        assert second.block_count > 0
        assert second.reused_node_ids, "Repeated concepts should reuse existing nodes"
        assert second.supported_edge_ids, "Repeated co-occurrence should reinforce an existing edge"

        with make_uow() as uow:
            mk5_nodes = uow.nodes.search_by_normalized_value("mk5", limit=10)
            assert mk5_nodes, "The reusable block 'mk5' should exist as a durable node"

            events = uow.graph_events.list_for_message(first.message_id)
            assert events, "Ingest should leave message-scoped graph events"

            revision_candidates = uow.edges.list_revision_candidates(min_contradiction_pressure=0.0, limit=50)
            assert isinstance(revision_candidates, list)


if __name__ == "__main__":
    main()
