import uuid
from datetime import datetime, timezone

from memory.db import connection_context
from memory.stores.topic_store import TopicStore


class ChatProfileEvidenceStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic(self, topic: str | None, topic_id: str | None) -> tuple[str | None, str | None]:
        normalized_topic = " ".join((topic or "").strip().split()) or None
        resolved_topic_id = topic_id
        if not resolved_topic_id and normalized_topic and normalized_topic.lower() != "general":
            resolved_topic_id = self.topic_store.ensure_topic(
                normalized_topic,
                source="ChatProfileEvidenceStore",
                confidence=0.65,
            )
        if resolved_topic_id and (not normalized_topic or normalized_topic.lower() == "general"):
            topic_row = self.topic_store.get_topic(resolved_topic_id)
            normalized_topic = str((topic_row or {}).get("summary") or (topic_row or {}).get("name") or "").strip() or None
        return normalized_topic, resolved_topic_id

    def add(
        self,
        *,
        source_message_id: str | None,
        response_message_id: str | None,
        evidence_text: str,
        confidence: float | None = None,
        topic: str | None = None,
        topic_id: str | None = None,
        candidate_content: str | None = None,
        source_strength: str | None = None,
        direct_confirm: bool = False,
    ) -> dict:
        evidence_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        resolved_topic, resolved_topic_id = self._resolve_topic(topic, topic_id)

        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO chat_profile_evidence (
                    id,
                    source_message_id,
                    response_message_id,
                    topic,
                    topic_id,
                    candidate_content,
                    source_strength,
                    evidence_text,
                    confidence,
                    direct_confirm,
                    applied_to_memory,
                    linked_profile_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
                """,
                (
                    evidence_id,
                    source_message_id,
                    response_message_id,
                    resolved_topic,
                    resolved_topic_id,
                    candidate_content,
                    source_strength,
                    evidence_text,
                    confidence,
                    1 if direct_confirm else 0,
                    now,
                ),
            )

        return {
            "id": evidence_id,
            "source_message_id": source_message_id,
            "response_message_id": response_message_id,
            "topic": resolved_topic,
            "topic_id": resolved_topic_id,
            "candidate_content": candidate_content,
            "source_strength": source_strength,
            "evidence_text": evidence_text,
            "confidence": confidence,
            "direct_confirm": 1 if direct_confirm else 0,
            "applied_to_memory": 0,
            "linked_profile_id": None,
            "created_at": now,
        }

    def list_candidate_evidence(self) -> list[dict]:
        with connection_context() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM chat_profile_evidence
                WHERE candidate_content IS NOT NULL
                  AND (topic_id IS NOT NULL OR topic IS NOT NULL)
                  AND (linked_profile_id IS NULL OR linked_profile_id = '')
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_applied(
        self,
        evidence_id: str,
        linked_profile_id: str | None = None,
    ) -> None:
        with connection_context() as conn:
            conn.execute(
                """
                UPDATE chat_profile_evidence
                SET applied_to_memory = 1,
                    linked_profile_id = COALESCE(?, linked_profile_id)
                WHERE id = ?
                """,
                (linked_profile_id, evidence_id),
            )

    def link_profile_for_candidate(
        self,
        candidate_content: str,
        profile_id: str,
        topic_id: str | None = None,
        topic: str | None = None,
    ) -> int:
        with connection_context() as conn:
            if topic_id:
                cursor = conn.execute(
                    """
                    UPDATE chat_profile_evidence
                    SET linked_profile_id = ?,
                        applied_to_memory = 1
                    WHERE topic_id = ?
                      AND candidate_content = ?
                      AND (linked_profile_id IS NULL OR linked_profile_id = '')
                    """,
                    (profile_id, topic_id, candidate_content),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE chat_profile_evidence
                    SET linked_profile_id = ?,
                        applied_to_memory = 1
                    WHERE topic = ?
                      AND candidate_content = ?
                      AND (linked_profile_id IS NULL OR linked_profile_id = '')
                    """,
                    (profile_id, topic, candidate_content),
                )
            return int(cursor.rowcount or 0)
