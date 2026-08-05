from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from core.entities.node_pointer import NodePointer
from storage.repositories.node_pointer_repository import NodePointerRepository
from storage.sqlite.common import as_bool, dumps_json, fetch_all, fetch_one, loads_json


class SqliteNodePointerRepository(NodePointerRepository):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ping(self) -> None:
        self.connection.execute("SELECT 1").fetchone()

    def add(self, pointer: NodePointer) -> NodePointer:
        cursor = self.connection.execute(
            """
            INSERT INTO node_pointers (
                pointer_uid, owner_node_id, referenced_node_id, pointer_type,
                pointer_slot, detail_json, created_from_event_id, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pointer.pointer_uid,
                pointer.owner_node_id,
                pointer.referenced_node_id,
                pointer.pointer_type,
                pointer.pointer_slot,
                dumps_json(pointer.detail),
                pointer.created_from_event_id,
                int(pointer.is_active),
            ),
        )
        return self.get_by_id(int(cursor.lastrowid)) or pointer

    def get_by_id(self, pointer_id: int) -> NodePointer | None:
        row = fetch_one(self.connection, "SELECT * FROM node_pointers WHERE id = ?", (pointer_id,))
        return _row_to_node_pointer(row) if row else None

    def find_active(
        self,
        owner_node_id: int,
        referenced_node_id: int,
        pointer_type: str,
        *,
        pointer_slot: str | None = None,
    ) -> NodePointer | None:
        if pointer_slot is None:
            row = fetch_one(
                self.connection,
                """
                SELECT * FROM node_pointers
                WHERE owner_node_id = ?
                  AND referenced_node_id = ?
                  AND pointer_type = ?
                  AND pointer_slot IS NULL
                  AND is_active = 1
                LIMIT 1
                """,
                (owner_node_id, referenced_node_id, pointer_type),
            )
        else:
            row = fetch_one(
                self.connection,
                """
                SELECT * FROM node_pointers
                WHERE owner_node_id = ?
                  AND referenced_node_id = ?
                  AND pointer_type = ?
                  AND pointer_slot = ?
                  AND is_active = 1
                LIMIT 1
                """,
                (owner_node_id, referenced_node_id, pointer_type, pointer_slot),
            )
        return _row_to_node_pointer(row) if row else None

    def list_by_owner(self, owner_node_id: int, *, active_only: bool = True) -> Sequence[NodePointer]:
        sql = "SELECT * FROM node_pointers WHERE owner_node_id = ?"
        params: list[object] = [owner_node_id]
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY id ASC"
        rows = fetch_all(self.connection, sql, params)
        return [_row_to_node_pointer(row) for row in rows]

    def list_referencing(self, referenced_node_id: int, *, active_only: bool = True) -> Sequence[NodePointer]:
        sql = "SELECT * FROM node_pointers WHERE referenced_node_id = ?"
        params: list[object] = [referenced_node_id]
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY id ASC"
        rows = fetch_all(self.connection, sql, params)
        return [_row_to_node_pointer(row) for row in rows]

    def update_owner(self, pointer_id: int, owner_node_id: int) -> None:
        self.connection.execute(
            "UPDATE node_pointers SET owner_node_id = ? WHERE id = ?",
            (owner_node_id, pointer_id),
        )

    def update_referenced(self, pointer_id: int, referenced_node_id: int) -> None:
        self.connection.execute(
            "UPDATE node_pointers SET referenced_node_id = ? WHERE id = ?",
            (referenced_node_id, pointer_id),
        )

    def update_detail(self, pointer_id: int, detail: dict) -> None:
        self.connection.execute(
            "UPDATE node_pointers SET detail_json = ? WHERE id = ?",
            (dumps_json(detail), pointer_id),
        )

    def deactivate(self, pointer_id: int) -> None:
        self.connection.execute("UPDATE node_pointers SET is_active = 0 WHERE id = ?", (pointer_id,))


def _row_to_node_pointer(row: sqlite3.Row) -> NodePointer:
    return NodePointer(
        id=int(row["id"]),
        pointer_uid=str(row["pointer_uid"]),
        owner_node_id=int(row["owner_node_id"]),
        referenced_node_id=int(row["referenced_node_id"]),
        pointer_type=str(row["pointer_type"]),
        pointer_slot=row["pointer_slot"],
        detail=loads_json(row["detail_json"], default={}),
        created_from_event_id=row["created_from_event_id"],
        created_at=row["created_at"],
        is_active=as_bool(row["is_active"]),
    )
