import uuid
from datetime import datetime, timezone

from memory.stores.topic_store import TopicStore
from project_analysis.stores.db import get_conn


class ProjectProfileEvidenceStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic(self, topic: str | None, topic_id: str | None) -> tuple[str | None, str | None]:
        normalized_topic = " ".join((topic or "").strip().split()) or None
        resolved_topic_id = topic_id
        if not resolved_topic_id and normalized_topic and normalized_topic.lower() != "general":
            resolved_topic_id = self.topic_store.ensure_topic(
                normalized_topic,
                source="ProjectProfileEvidenceStore",
                confidence=0.65,
            )
        if resolved_topic_id and (not normalized_topic or normalized_topic.lower() == "general"):
            topic_row = self.topic_store.get_topic(resolved_topic_id)
            normalized_topic = str((topic_row or {}).get("summary") or (topic_row or {}).get("name") or "").strip() or None
        return normalized_topic, resolved_topic_id

    def add(
        self,
        project_id: str,
        source_file_path: str,
        evidence_type: str,
        evidence_text: str,
        confidence: float | None = None,
        topic: str | None = None,
        topic_id: str | None = None,
        candidate_content: str | None = None,
        source_strength: str | None = None,
    ) -> dict:
        evidence_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        resolved_topic, resolved_topic_id = self._resolve_topic(topic, topic_id)

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_profile_evidence (
                    id,
                    project_id,
                    source_file_path,
                    evidence_type,
                    topic,
                    topic_id,
                    candidate_content,
                    source_strength,
                    evidence_text,
                    confidence,
                    applied_to_memory,
                    linked_profile_id,
                    linked_correction_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?)
                """,
                (
                    evidence_id,
                    project_id,
                    source_file_path,
                    evidence_type,
                    resolved_topic,
                    resolved_topic_id,
                    candidate_content,
                    source_strength,
                    evidence_text,
                    confidence,
                    now,
                ),
            )
            conn.commit()

        return {
            "id": evidence_id,
            "project_id": project_id,
            "source_file_path": source_file_path,
            "evidence_type": evidence_type,
            "topic": resolved_topic,
            "topic_id": resolved_topic_id,
            "candidate_content": candidate_content,
            "source_strength": source_strength,
            "evidence_text": evidence_text,
            "confidence": confidence,
            "applied_to_memory": 0,
            "linked_profile_id": None,
            "linked_correction_id": None,
            "created_at": now,
        }

    def delete_by_project(self, project_id: str) -> None:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM project_profile_evidence WHERE project_id = ?",
                (project_id,),
            )
            conn.commit()

    def list_by_project(self, project_id: str) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_profile_evidence
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_unapplied_by_project(self, project_id: str) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_profile_evidence
                WHERE project_id = ?
                  AND applied_to_memory = 0
                ORDER BY created_at ASC
                """,
                (project_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_candidate_evidence(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_profile_evidence
                WHERE evidence_type = 'profile_candidate'
                  AND candidate_content IS NOT NULL
                  AND (topic_id IS NOT NULL OR topic IS NOT NULL)
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def mark_applied(
        self,
        evidence_id: str,
        linked_profile_id: str | None = None,
        linked_correction_id: str | None = None,
    ) -> None:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE project_profile_evidence
                SET applied_to_memory = 1,
                    linked_profile_id = COALESCE(?, linked_profile_id),
                    linked_correction_id = COALESCE(?, linked_correction_id)
                WHERE id = ?
                """,
                (linked_profile_id, linked_correction_id, evidence_id),
            )
            conn.commit()

    def link_profile_for_candidate(
        self,
        candidate_content: str,
        profile_id: str,
        topic_id: str | None = None,
        topic: str | None = None,
    ) -> int:
        with get_conn() as conn:
            if topic_id:
                cursor = conn.execute(
                    """
                    UPDATE project_profile_evidence
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
                    UPDATE project_profile_evidence
                    SET linked_profile_id = ?,
                        applied_to_memory = 1
                    WHERE evidence_type = 'profile_candidate'
                      AND topic = ?
                      AND candidate_content = ?
                      AND (linked_profile_id IS NULL OR linked_profile_id = '')
                    """,
                    (profile_id, topic, candidate_content),
                )
            conn.commit()
            return int(cursor.rowcount or 0)
