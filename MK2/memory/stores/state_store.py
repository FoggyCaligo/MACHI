from memory.db import connection_context, utc_now


class StateStore:
    def set_state(self, key: str, value: str, source: str = "user_explicit"):
        now = utc_now()
        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO states (key, value, updated_at, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at,
                    source = excluded.source
                """,
                (key, value, now, source),
            )

    def delete_state(self, key: str):
        with connection_context() as conn:
            conn.execute("DELETE FROM states WHERE key = ?", (key,))

    def get_state(self, key: str):
        with connection_context() as conn:
            row = conn.execute("SELECT * FROM states WHERE key = ?", (key,)).fetchone()
            return dict(row) if row else None

    def get_all(self):
        with connection_context() as conn:
            rows = conn.execute("SELECT * FROM states ORDER BY updated_at DESC").fetchall()
            return [dict(r) for r in rows]

    def set_active_topic(self, topic_id: str, summary: str, source: str = "topic_router") -> None:
        self.set_state("active_topic_id", topic_id, source=source)
        self.set_state("active_topic_summary", summary, source=source)

    def get_active_topic_id(self) -> str | None:
        row = self.get_state("active_topic_id")
        value = (row or {}).get("value")
        return str(value).strip() or None