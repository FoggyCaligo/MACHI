from __future__ import annotations

from pathlib import Path

from core.entities.chat_message import ChatMessage
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from storage.sqlite.unit_of_work import SqliteUnitOfWork


def _make_uow(tmp_path: Path, *, node_event_cap: int | None = None, edge_event_cap: int | None = None) -> SqliteUnitOfWork:
    schema_path = Path(__file__).resolve().parents[2] / "storage" / "schema.sql"
    return SqliteUnitOfWork(
        tmp_path / "memory.db",
        schema_path=schema_path,
        initialize_schema=True,
        node_event_cap=node_event_cap,
        edge_event_cap=edge_event_cap,
    )


def test_graph_event_repository_caps_node_history_but_keeps_creation_event(tmp_path: Path) -> None:
    with _make_uow(tmp_path, node_event_cap=2) as uow:
        message = uow.chat_messages.add(
            ChatMessage(
                message_uid="msg-1",
                session_id="s1",
                turn_index=1,
                role="user",
                content="plate armor",
            )
        )
        created = uow.graph_events.add(
            GraphEvent(
                event_uid="evt-created",
                event_type="node_created",
                message_id=message.id,
                trigger_node_id=11,
                effect={"reason": "fixture"},
            )
        )
        uow.graph_events.add(
            GraphEvent(
                event_uid="evt-supported-1",
                event_type="node_supported",
                message_id=message.id,
                trigger_node_id=11,
                effect={"step": 1},
            )
        )
        uow.graph_events.add(
            GraphEvent(
                event_uid="evt-supported-2",
                event_type="node_supported",
                message_id=message.id,
                trigger_node_id=11,
                effect={"step": 2},
            )
        )
        uow.graph_events.add(
            GraphEvent(
                event_uid="evt-supported-3",
                event_type="node_supported",
                message_id=message.id,
                trigger_node_id=11,
                effect={"step": 3},
            )
        )

        scoped = list(uow.graph_events.list_for_node(11, limit=10))
        assert [event.event_type for event in scoped] == ["node_supported", "node_supported", "node_created"]
        assert [event.effect.get("step") for event in scoped[:2]] == [3, 2]
        assert scoped[-1].id == created.id
        assert uow.graph_events.get_by_uid("evt-supported-1") is None


def test_graph_event_repository_caps_edge_history_but_keeps_edge_created(tmp_path: Path) -> None:
    with _make_uow(tmp_path, edge_event_cap=2) as uow:
        message = uow.chat_messages.add(
            ChatMessage(
                message_uid="msg-1",
                session_id="s1",
                turn_index=1,
                role="user",
                content="plate armor",
            )
        )
        source = uow.nodes.add(
            Node(
                node_uid="node-1",
                address_hash="hash-1",
                node_kind="concept",
                raw_value="사람",
                normalized_value="사람",
            )
        )
        target = uow.nodes.add(
            Node(
                node_uid="node-2",
                address_hash="hash-2",
                node_kind="concept",
                raw_value="재용",
                normalized_value="재용",
            )
        )
        edge = uow.edges.add(
            Edge(
                edge_uid="edge-1",
                source_node_id=source.id or 0,
                target_node_id=target.id or 0,
                edge_family="concept",
                connect_type="flow",
                relation_detail={"connect_semantics": "specialized_concept"},
            )
        )
        created = uow.graph_events.add(
            GraphEvent(
                event_uid="evt-edge-created",
                event_type="edge_created",
                message_id=message.id,
                trigger_edge_id=edge.id,
                effect={"reason": "fixture"},
            )
        )
        for step in range(1, 4):
            uow.graph_events.add(
                GraphEvent(
                    event_uid=f"evt-edge-supported-{step}",
                    event_type="edge_supported",
                    message_id=message.id,
                    trigger_edge_id=edge.id,
                    effect={"step": step},
                )
            )

        scoped = list(uow.graph_events.list_for_edge(edge.id or 0, limit=10))
        assert [event.event_type for event in scoped] == ["edge_supported", "edge_supported", "edge_created"]
        assert [event.effect.get("step") for event in scoped[:2]] == [3, 2]
        assert scoped[-1].id == created.id
        assert uow.graph_events.get_by_uid("evt-edge-supported-1") is None
