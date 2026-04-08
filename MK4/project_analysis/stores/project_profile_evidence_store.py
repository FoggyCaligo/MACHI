import uuid
from datetime import datetime, timezone

from project_analysis.stores.db import get_conn


class ProjectProfileEvidenceStore:
    def add(
        self,
        project_id: str,
        source_file_path: str,
        evidence_type: str,
        evidence_text: str,
        confidence: float | None = None,
        topic: str | None = None,
        candidate_content: str | None = None,
        source_strength: str | None = None,
    ) -> dict:
        evidence_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_profile_evidence (
                    id,
                    project_id,
                    source_file_path,
                    evidence_type,
                    topic,
                    candidate_content,
                    source_strength,
                    evidence_text,
                    confidence,
                    applied_to_memory,
                    linked_profile_id,
                    linked_correction_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?)
                """,
                (
                    evidence_id,
                    project_id,
                    source_file_path,
                    evidence_type,
                    topic,
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
            "topic": topic,
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
                  AND topic IS NOT NULL
                  AND candidate_content IS NOT NULL
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
        topic: str,
        candidate_content: str,
        profile_id: str,
    ) -> int:
        with get_conn() as conn:
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