import uuid
from typing import Any

from memory.db import connection_context, utc_now


class ProfileStore:
    def _build_topic_clause(self, *, topic: str | None = None, topic_id: str | None = None) -> tuple[str, tuple]:
        if topic_id:
            return "topic_id = ?", (topic_id,)
        return "topic = ?", (topic or "general",)

    def get_active_by_topic(self, topic: str | None = None, topic_id: str | None = None) -> dict[str, Any] | None:
        clause, values = self._build_topic_clause(topic=topic, topic_id=topic_id)
        with connection_context() as conn:
            row = conn.execute(
                f"SELECT * FROM profiles WHERE {clause} AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                values,
            ).fetchone()
            return dict(row) if row else None

    def get_active_profiles(self, exclude_general: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM profiles WHERE status = 'active'"
        params: tuple = ()
        if exclude_general:
            query += " AND COALESCE(topic, '') != 'general'"
        query += " ORDER BY updated_at DESC"
        with connection_context() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_recent_history(self, topic: str | None = None, topic_id: str | None = None, limit: int = 2) -> list[dict[str, Any]]:
        clause, values = self._build_topic_clause(topic=topic, topic_id=topic_id)
        with connection_context() as conn:
            rows = conn.execute(
                f"SELECT * FROM profiles WHERE {clause} AND status = 'superseded' ORDER BY updated_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 5, include_general: bool = True) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        sql = """
                SELECT * FROM profiles
                WHERE status = 'active' AND (topic LIKE ? OR content LIKE ?)
                """
        params = [pattern, pattern]
        if not include_general:
            sql += " AND COALESCE(topic, '') != 'general'"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with connection_context() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def insert_profile(self, topic: str, content: str, source: str, confidence: float = 1.0, topic_id: str | None = None):
        now = utc_now()
        clause, values = self._build_topic_clause(topic=topic, topic_id=topic_id)
        with connection_context() as conn:
            active = conn.execute(
                f"SELECT * FROM profiles WHERE {clause} AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                values,
            ).fetchone()
            version_no = 1
            if active:
                version_no = int(active['version_no']) + 1
                conn.execute(
                    "UPDATE profiles SET status = 'superseded', updated_at = ? WHERE id = ?",
                    (now, active['id']),
                )
            new_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO profiles (id, topic_id, topic, content, confidence, source, version_no, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (new_id, topic_id, topic, content, confidence, source, version_no, now, now),
            )
        self.trim_history(topic=topic, topic_id=topic_id, keep_superseded=2)
        return new_id

    def trim_history(self, topic: str | None = None, topic_id: str | None = None, keep_superseded: int = 2):
        clause, values = self._build_topic_clause(topic=topic, topic_id=topic_id)
        with connection_context() as conn:
            rows = conn.execute(
                f"SELECT id FROM profiles WHERE {clause} AND status = 'superseded' ORDER BY updated_at DESC",
                values,
            ).fetchall()
            for row in rows[keep_superseded:]:
                conn.execute("DELETE FROM profiles WHERE id = ?", (row['id'],))
