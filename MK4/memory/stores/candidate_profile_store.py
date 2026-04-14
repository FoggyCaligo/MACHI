import uuid
from typing import Any

from memory.db import connection_context, utc_now
from memory.stores.topic_store import TopicStore


class CandidateProfileStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic_id(self, *, topic: str | None = None, topic_id: str | None = None, create_if_missing: bool = False) -> str | None:
        if topic_id:
            return topic_id
        if not topic or str(topic).strip().lower() == "general":
            return None
        if create_if_missing:
            return self.topic_store.ensure_topic(topic, source="candidate_profile_store", confidence=0.65)
        return self.topic_store.find_exact_topic_id(topic)

    def _build_topic_clause(self, resolved_topic_id: str | None) -> tuple[str, tuple]:
        if resolved_topic_id:
            return "cp.topic_id = ?", (resolved_topic_id,)
        return "cp.topic_id IS NULL", ()

    def _base_select(self) -> str:
        return (
            "SELECT cp.*, t.name AS topic_name, t.summary AS topic_summary "
            "FROM candidate_profiles cp LEFT JOIN topics t ON cp.topic_id = t.id"
        )

    def list_active_by_topic(self, topic: str | None = None, topic_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        clause, values = self._build_topic_clause(resolved_topic_id)
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE {clause} AND cp.status = 'active' ORDER BY cp.support_score DESC, cp.updated_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_demoted_profile(
        self,
        *,
        topic: str | None,
        topic_id: str | None,
        content: str,
        source: str,
        confidence: float,
        support_score: float,
        source_profile_id: str | None = None,
    ) -> str:
        now = utc_now()
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        with connection_context() as conn:
            existing = None
            if source_profile_id:
                existing = conn.execute(
                    f"{self._base_select()} WHERE cp.source_profile_id = ? AND cp.status = 'active' LIMIT 1",
                    (source_profile_id,),
                ).fetchone()
            if not existing:
                clause, values = self._build_topic_clause(resolved_topic_id)
                existing = conn.execute(
                    f"{self._base_select()} WHERE {clause} AND cp.content = ? AND cp.status = 'active' LIMIT 1",
                    (*values, content),
                ).fetchone()
            if existing:
                candidate_id = str(existing['id'])
                conn.execute(
                    """
                    UPDATE candidate_profiles
                    SET content = ?, confidence = ?, support_score = ?, source = ?, source_profile_id = COALESCE(?, source_profile_id), updated_at = ?, status = 'active'
                    WHERE id = ?
                    """,
                    (content, confidence, support_score, source, source_profile_id, now, candidate_id),
                )
                return candidate_id

            candidate_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO candidate_profiles (
                    id, topic_id, content, confidence, support_score, source, source_profile_id, created_at, updated_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (candidate_id, resolved_topic_id, content, confidence, support_score, source, source_profile_id, now, now),
            )
            return candidate_id

    def archive_matching_active(self, *, topic: str | None, topic_id: str | None, content: str) -> int:
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        now = utc_now()
        with connection_context() as conn:
            if resolved_topic_id:
                cursor = conn.execute(
                    "UPDATE candidate_profiles SET status = 'promoted', updated_at = ? WHERE topic_id = ? AND content = ? AND status = 'active'",
                    (now, resolved_topic_id, content),
                )
            else:
                cursor = conn.execute(
                    "UPDATE candidate_profiles SET status = 'promoted', updated_at = ? WHERE topic_id IS NULL AND content = ? AND status = 'active'",
                    (now, content),
                )
            return int(cursor.rowcount or 0)
