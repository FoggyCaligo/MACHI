from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from core.entities.chat_message import ChatMessage
from storage.repositories.chat_message_repository import ChatMessageRepository
from storage.sqlite.common import dumps_json, fetch_all, fetch_one, loads_json, placeholders


class SqliteChatMessageRepository(ChatMessageRepository):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ping(self) -> None:
        self.connection.execute("SELECT 1").fetchone()

    def add(self, message: ChatMessage) -> ChatMessage:
        cursor = self.connection.execute(
            """
            INSERT INTO chat_messages (
                message_uid, session_id, turn_index, role, content, content_hash,
                attached_files_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_uid,
                message.session_id,
                message.turn_index,
                message.role,
                message.content,
                message.content_hash,
                dumps_json(message.attached_files),
                dumps_json(message.metadata),
            ),
        )
        return self.get_by_id(int(cursor.lastrowid)) or message

    def get_by_id(self, message_id: int) -> ChatMessage | None:
        row = fetch_one(self.connection, "SELECT * FROM chat_messages WHERE id = ?", (message_id,))
        return _row_to_chat_message(row) if row else None

    def get_by_uid(self, message_uid: str) -> ChatMessage | None:
        row = fetch_one(self.connection, "SELECT * FROM chat_messages WHERE message_uid = ?", (message_uid,))
        return _row_to_chat_message(row) if row else None

    def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
        before_turn_index: int | None = None,
        after_turn_index: int | None = None,
    ) -> Sequence[ChatMessage]:
        clauses = ["session_id = ?"]
        params: list[object] = [session_id]
        if before_turn_index is not None:
            clauses.append("turn_index < ?")
            params.append(before_turn_index)
        if after_turn_index is not None:
            clauses.append("turn_index > ?")
            params.append(after_turn_index)
        params.append(limit)
        rows = fetch_all(
            self.connection,
            f"""
            SELECT *
            FROM chat_messages
            WHERE {' AND '.join(clauses)}
            ORDER BY turn_index ASC, id ASC
            LIMIT ?
            """,
            params,
        )
        return [_row_to_chat_message(row) for row in rows]

    def list_by_ids(self, message_ids: Sequence[int]) -> Sequence[ChatMessage]:
        if not message_ids:
            return []
        rows = fetch_all(
            self.connection,
            f"SELECT * FROM chat_messages WHERE id IN ({placeholders(message_ids)})",
            list(message_ids),
        )
        by_id = {int(row["id"]): _row_to_chat_message(row) for row in rows}
        return [by_id[message_id] for message_id in message_ids if message_id in by_id]


def _row_to_chat_message(row: sqlite3.Row) -> ChatMessage:
    return ChatMessage(
        id=int(row["id"]),
        message_uid=str(row["message_uid"]),
        session_id=str(row["session_id"]),
        turn_index=int(row["turn_index"]),
        role=str(row["role"]),
        content=str(row["content"]),
        content_hash=row["content_hash"],
        attached_files=loads_json(row["attached_files_json"], default=[]),
        metadata=loads_json(row["metadata_json"], default={}),
        created_at=row["created_at"],
    )
