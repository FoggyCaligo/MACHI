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

    def get_state(self, key: str):
        with connection_context() as conn:
            row = conn.execute("SELECT * FROM states WHERE key = ?", (key,)).fetchone()
            return dict(row) if row else None

    def get_all(self):
        with connection_context() as conn:
            rows = conn.execute("SELECT * FROM states ORDER BY updated_at DESC").fetchall()
            return [dict(r) for r in rows]
