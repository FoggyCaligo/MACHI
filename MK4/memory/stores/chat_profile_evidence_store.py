import uuid

from memory.db import connection_context, utc_now


class ChatProfileEvidenceStore:
    def add(
        self,
        *,
        evidence_type: str = "profile_candidate",
        source_message_id: str | None = None,
        response_message_id: str | None = None,
        topic: str | None = None,
        topic_id: str | None = None,
        candidate_content: str | None = None,
        source_strength: str | None = None,
        evidence_text: str | None = None,
        confidence: float | None = None,
        memory_tier: str | None = None,
        direct_confirm: bool = False,
        applied_to_memory: int = 0,
        linked_profile_id: str | None = None,
        linked_correction_id: str | None = None,
    ) -> dict:
        evidence_id = str(uuid.uuid4())
        now = utc_now()
        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO chat_profile_evidence (
                    id,
                    evidence_type,
                    source_message_id,
                    response_message_id,
                    topic,
                    topic_id,
                    candidate_content,
                    source_strength,
                    evidence_text,
                    confidence,
                    memory_tier,
                    direct_confirm,
                    applied_to_memory,
                    linked_profile_id,
                    linked_correction_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    evidence_type,
                    source_message_id,
                    response_message_id,
                    topic,
                    topic_id,
                    candidate_content,
                    source_strength,
                    evidence_text,
                    confidence,
                    memory_tier,
                    1 if direct_confirm else 0,
                    applied_to_memory,
                    linked_profile_id,
                    linked_correction_id,
                    now,
                ),
            )
        return {
            "id": evidence_id,
            "evidence_type": evidence_type,
            "source_message_id": source_message_id,
            "response_message_id": response_message_id,
            "topic": topic,
            "topic_id": topic_id,
            "candidate_content": candidate_content,
            "source_strength": source_strength,
            "evidence_text": evidence_text,
            "confidence": confidence,
            "memory_tier": memory_tier,
            "direct_confirm": 1 if direct_confirm else 0,
            "applied_to_memory": applied_to_memory,
            "linked_profile_id": linked_profile_id,
            "linked_correction_id": linked_correction_id,
            "created_at": now,
        }

    def list_profile_evidence(self) -> list[dict]:
        with connection_context() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM chat_profile_evidence
                WHERE evidence_type = 'profile_candidate'
                  AND candidate_content IS NOT NULL
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def link_profile_for_candidate(
        self,
        *,
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
                    WHERE evidence_type = 'profile_candidate'
                      AND topic_id = ?
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
                    WHERE evidence_type = 'profile_candidate'
                      AND topic = ?
                      AND candidate_content = ?
                      AND (linked_profile_id IS NULL OR linked_profile_id = '')
                    """,
                    (profile_id, topic, candidate_content),
                )
            return int(cursor.rowcount or 0)

    def mark_applied(
        self,
        evidence_id: str,
        *,
        linked_profile_id: str | None = None,
        linked_correction_id: str | None = None,
    ) -> None:
        with connection_context() as conn:
            conn.execute(
                """
                UPDATE chat_profile_evidence
                SET applied_to_memory = 1,
                    linked_profile_id = COALESCE(?, linked_profile_id),
                    linked_correction_id = COALESCE(?, linked_correction_id)
                WHERE id = ?
                """,
                (linked_profile_id, linked_correction_id, evidence_id),
            )
