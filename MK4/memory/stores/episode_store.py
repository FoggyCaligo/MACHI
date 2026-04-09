import uuid
from typing import Any

from memory.db import connection_context, utc_now
from memory.stores.topic_store import TopicStore


class EpisodeStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic_id(self, *, topic: str | None = None, topic_id: str | None = None, create_if_missing: bool = False) -> str | None:
        if topic_id:
            return topic_id
        if not topic or str(topic).strip().lower() == "general":
            return None
        if create_if_missing:
            return self.topic_store.ensure_topic(topic, source="episode_store", confidence=0.6)
        return self.topic_store.find_exact_topic_id(topic)

    def _base_select(self) -> str:
        return (
            "SELECT e.*, t.name AS topic_name, t.summary AS topic_summary "
            "FROM episodes e LEFT JOIN topics t ON e.topic_id = t.id"
        )

    def create_episode(self, topic: str, summary: str, raw_ref: str | None = None, importance: float = 0.5, topic_id: str | None = None):
        episode_id = str(uuid.uuid4())
        now = utc_now()
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=True)
        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO episodes (id, topic_id, summary, raw_ref, importance, last_referenced_at, created_at, state, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0)
                """,
                (episode_id, resolved_topic_id, summary, raw_ref, importance, now, now),
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
                f"{self._base_select()} WHERE e.state != 'dropped' AND (COALESCE(t.summary, '') LIKE ? OR COALESCE(t.name, '') LIKE ? OR e.summary LIKE ? OR COALESCE(e.raw_ref, '') LIKE ?) ORDER BY e.pinned DESC, e.importance DESC, e.last_referenced_at DESC LIMIT ?",
                (pattern, pattern, pattern, pattern, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent(self, limit: int = 5):
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE e.state != 'dropped' ORDER BY e.created_at DESC LIMIT ?",
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
        return None
