import json
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

    def _normalize_paths(self, source_file_paths: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_path in source_file_paths or []:
            path = str(raw_path or "").replace("\\", "/").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            normalized.append(path)
        return normalized

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
        direct_confirm: bool = False,
        memory_tier: str | None = None,
        source_file_paths: list[str] | None = None,
        source_file_hashes: dict[str, str] | None = None,
    ) -> dict:
        evidence_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        resolved_topic, resolved_topic_id = self._resolve_topic(topic, topic_id)
        normalized_path = str(source_file_path or "").replace("\\", "/").strip()
        normalized_paths = self._normalize_paths(source_file_paths)
        if not normalized_paths and normalized_path:
            normalized_paths = [normalized_path]
        normalized_hashes = {
            str(path).replace("\\", "/").strip(): str(value or "").strip()
            for path, value in (source_file_hashes or {}).items()
            if str(path or "").strip() and str(value or "").strip()
        }

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_profile_evidence (
                    id, project_id, source_file_path, evidence_type, topic, topic_id,
                    candidate_content, source_strength, evidence_text, confidence,
                    applied_to_memory, linked_profile_id, linked_correction_id, direct_confirm, memory_tier,
                    source_file_paths_json, source_file_hashes_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id, project_id, normalized_path, evidence_type, resolved_topic, resolved_topic_id,
                    candidate_content, source_strength, evidence_text, confidence,
                    1 if direct_confirm else 0, memory_tier,
                    json.dumps(normalized_paths, ensure_ascii=False),
                    json.dumps(normalized_hashes, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()

        return {
            "id": evidence_id,
            "project_id": project_id,
            "source_file_path": normalized_path,
            "source_file_paths": normalized_paths,
            "source_file_hashes": normalized_hashes,
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
            "direct_confirm": 1 if direct_confirm else 0,
            "memory_tier": memory_tier,
            "created_at": now,
        }

    def _decode_row(self, row) -> dict:
        item = dict(row)
        try:
            source_file_paths = json.loads(item.get("source_file_paths_json") or "[]")
            if not isinstance(source_file_paths, list):
                source_file_paths = []
        except Exception:
            source_file_paths = []
        source_file_paths = self._normalize_paths(source_file_paths)
        if not source_file_paths and str(item.get("source_file_path") or "").strip():
            source_file_paths = [str(item.get("source_file_path") or "").replace("\\", "/").strip()]

        try:
            source_file_hashes = json.loads(item.get("source_file_hashes_json") or "{}")
            if not isinstance(source_file_hashes, dict):
                source_file_hashes = {}
        except Exception:
            source_file_hashes = {}

        item["source_file_paths"] = source_file_paths
        item["source_file_hashes"] = {
            str(path).replace("\\", "/").strip(): str(value or "").strip()
            for path, value in source_file_hashes.items()
            if str(path or "").strip() and str(value or "").strip()
        }
        return item

    def delete_by_project(self, project_id: str) -> None:
        with get_conn() as conn:
            conn.execute("DELETE FROM project_profile_evidence WHERE project_id = ?", (project_id,))
            conn.commit()

    def delete_by_project_paths(self, project_id: str, source_file_paths: list[str]) -> int:
        normalized_paths = self._normalize_paths(source_file_paths)
        if not normalized_paths:
            return 0
        placeholders = ",".join("?" * len(normalized_paths))
        with get_conn() as conn:
            cursor = conn.execute(
                f"DELETE FROM project_profile_evidence WHERE project_id = ? AND source_file_path IN ({placeholders})",
                (project_id, *normalized_paths),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

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
        return [self._decode_row(row) for row in rows]

    def list_by_project_paths(self, project_id: str, source_file_paths: list[str]) -> list[dict]:
        normalized_paths = self._normalize_paths(source_file_paths)
        if not normalized_paths:
            return []
        placeholders = ",".join("?" * len(normalized_paths))
        with get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM project_profile_evidence
                WHERE project_id = ?
                  AND source_file_path IN ({placeholders})
                ORDER BY created_at DESC
                """,
                (project_id, *normalized_paths),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

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
        return [self._decode_row(row) for row in rows]

    def list_profile_evidence(self) -> list[dict]:
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
        return [self._decode_row(row) for row in rows]

    def list_candidate_evidence(self) -> list[dict]:
        return self.list_profile_evidence()

    def mark_applied(self, evidence_id: str, linked_profile_id: str | None = None, linked_correction_id: str | None = None) -> None:
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

    def link_profile_for_candidate(self, candidate_content: str, profile_id: str, topic_id: str | None = None, topic: str | None = None) -> int:
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
