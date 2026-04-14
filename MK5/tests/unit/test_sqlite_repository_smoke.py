from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.entities.chat_message import ChatMessage
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from core.entities.node_pointer import NodePointer
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "memory.db"
        schema_path = ROOT / "storage" / "schema.sql"

        with SqliteUnitOfWork(db_path, schema_path=schema_path, initialize_schema=True) as uow:
            message = uow.chat_messages.add(
                ChatMessage(
                    message_uid="msg-1",
                    session_id="session-1",
                    turn_index=1,
                    role="user",
                    content="안녕",
                    attached_files=[],
                    metadata={"source": "smoke"},
                )
            )
            event = uow.graph_events.add(
                GraphEvent(
                    event_uid="evt-1",
                    event_type="message_ingested",
                    message_id=message.id,
                    input_text=message.content,
                )
            )
            node_a = uow.nodes.add(
                Node(
                    node_uid="node-1",
                    address_hash="hash-a",
                    node_kind="concept",
                    raw_value="안녕",
                    normalized_value="안녕",
                    payload={"kind": "greeting"},
                    created_from_event_id=event.id,
                )
            )
            node_b = uow.nodes.add(
                Node(
                    node_uid="node-2",
                    address_hash="hash-b",
                    node_kind="concept",
                    raw_value="인사",
                    normalized_value="인사",
                    payload={"kind": "category"},
                    created_from_event_id=event.id,
                )
            )
            edge = uow.edges.add(
                Edge(
                    edge_uid="edge-1",
                    source_node_id=node_a.id or 0,
                    target_node_id=node_b.id or 0,
                    edge_type="is_a",
                    relation_detail={"reason": "smoke"},
                    created_from_event_id=event.id,
                )
            )
            pointer = uow.node_pointers.add(
                NodePointer(
                    pointer_uid="ptr-1",
                    owner_node_id=node_a.id or 0,
                    referenced_node_id=node_b.id or 0,
                    pointer_type="support_reference",
                    created_from_event_id=event.id,
                )
            )

            assert uow.chat_messages.get_by_uid("msg-1") is not None
            assert uow.graph_events.get_by_uid("evt-1") is not None
            assert uow.nodes.get_by_address_hash("hash-a") is not None
            assert uow.edges.find_active_relation(node_a.id or 0, node_b.id or 0, "is_a") is not None
            assert uow.node_pointers.find_active(node_a.id or 0, node_b.id or 0, "support_reference") is not None

            uow.edges.bump_conflict(edge.id or 0, trust_delta=-0.2)
            uow.edges.set_revision_candidate(edge.id or 0, flag=True)
            revised = uow.edges.list_revision_candidates(min_contradiction_pressure=1.0, limit=10)
            assert revised
            uow.nodes.update_scores(node_a.id or 0, trust_score=0.8, revision_state="under_review")
            reviewed = uow.nodes.get_by_id(node_a.id or 0)
            assert reviewed is not None and reviewed.revision_state == "under_review"
            assert pointer.id is not None


if __name__ == "__main__":
    main()
