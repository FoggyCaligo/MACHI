import uuid
from typing import Any

from memory.db import connection_context, utc_now


class EpisodeStore:
    def create_episode(self, topic: str, summary: str, raw_ref: str | None = None, importance: float = 0.5):
        episode_id = str(uuid.uuid4())
        now = utc_now()
        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO episodes (id, topic, summary, raw_ref, importance, last_referenced_at, created_at, state, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0)
                """,
                (episode_id, topic, summary, raw_ref, importance, now, now),
            )
        return episode_id

    def reference(self, episode_id: str):
        with connection_context() as conn:
            conn.execute(
                "UPDATE episodes SET last_referenced_at = ? WHERE id = ?",
                (utc_now(), episode_id),
            )

    def find_relevant(self, query: str, limit: int = 5):
        pattern = f"%{query}%"
        with connection_context() as conn:
            rows = conn.execute(
                """
                SELECT * FROM episodes
                WHERE state != 'dropped' AND (
                    topic LIKE ? OR summary LIKE ? OR COALESCE(raw_ref, '') LIKE ?
                )
                ORDER BY pinned DESC, importance DESC, last_referenced_at DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent(self, limit: int = 5):
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE state != 'dropped' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_compressed(self, episode_id: str):
        with connection_context() as conn:
            conn.execute("UPDATE episodes SET state = 'compressed' WHERE id = ? AND pinned = 0", (episode_id,))

    def mark_dropped(self, episode_id: str):
        with connection_context() as conn:
            conn.execute("UPDATE episodes SET state = 'dropped' WHERE id = ? AND pinned = 0", (episode_id,))

    def transition_state(self):
        # retention policy에서 세부 조건 판단 후 여기 메서드 호출 예정
        return None
