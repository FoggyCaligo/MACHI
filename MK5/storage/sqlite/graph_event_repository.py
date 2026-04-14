from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from core.entities.graph_event import GraphEvent
from storage.repositories.graph_event_repository import GraphEventRepository
from storage.sqlite.common import dumps_json, fetch_all, fetch_one, loads_json, placeholders


class SqliteGraphEventRepository(GraphEventRepository):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ping(self) -> None:
        self.connection.execute("SELECT 1").fetchone()

    def add(self, event: GraphEvent) -> GraphEvent:
        cursor = self.connection.execute(
            """
            INSERT INTO graph_events (
                event_uid, event_type, message_id, trigger_node_id, trigger_edge_id,
                input_text, parsed_input_json, effect_json, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_uid,
                event.event_type,
                event.message_id,
                event.trigger_node_id,
                event.trigger_edge_id,
                event.input_text,
                dumps_json(event.parsed_input),
                dumps_json(event.effect),
                event.note,
            ),
        )
        return self.get_by_id(int(cursor.lastrowid)) or event

    def get_by_id(self, event_id: int) -> GraphEvent | None:
        row = fetch_one(self.connection, "SELECT * FROM graph_events WHERE id = ?", (event_id,))
        return _row_to_graph_event(row) if row else None

    def get_by_uid(self, event_uid: str) -> GraphEvent | None:
        row = fetch_one(self.connection, "SELECT * FROM graph_events WHERE event_uid = ?", (event_uid,))
        return _row_to_graph_event(row) if row else None

    def list_for_message(self, message_id: int) -> Sequence[GraphEvent]:
        rows = fetch_all(
            self.connection,
            "SELECT * FROM graph_events WHERE message_id = ? ORDER BY id ASC",
            (message_id,),
        )
        return [_row_to_graph_event(row) for row in rows]

    def list_for_node(self, node_id: int, *, limit: int = 100) -> Sequence[GraphEvent]:
        rows = fetch_all(
            self.connection,
            """
            SELECT * FROM graph_events
            WHERE trigger_node_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (node_id, limit),
        )
        return [_row_to_graph_event(row) for row in rows]

    def list_for_edge(self, edge_id: int, *, limit: int = 100) -> Sequence[GraphEvent]:
        rows = fetch_all(
            self.connection,
            """
            SELECT * FROM graph_events
            WHERE trigger_edge_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (edge_id, limit),
        )
        return [_row_to_graph_event(row) for row in rows]

    def list_recent(
        self,
        *,
        event_types: Sequence[str] | None = None,
        limit: int = 100,
    ) -> Sequence[GraphEvent]:
        params: list[object] = []
        clauses: list[str] = []
        if event_types:
            clauses.append(f"event_type IN ({placeholders(event_types)})")
            params.extend(event_types)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = fetch_all(
            self.connection,
            f"""
            SELECT * FROM graph_events
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        )
        return [_row_to_graph_event(row) for row in rows]


def _row_to_graph_event(row: sqlite3.Row) -> GraphEvent:
    return GraphEvent(
        id=int(row["id"]),
        event_uid=str(row["event_uid"]),
        event_type=str(row["event_type"]),
        message_id=row["message_id"],
        trigger_node_id=row["trigger_node_id"],
        trigger_edge_id=row["trigger_edge_id"],
        input_text=row["input_text"],
        parsed_input=loads_json(row["parsed_input_json"], default={}),
        effect=loads_json(row["effect_json"], default={}),
        note=row["note"],
        created_at=row["created_at"],
    )
