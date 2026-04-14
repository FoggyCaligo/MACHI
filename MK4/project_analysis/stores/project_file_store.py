import hashlib
import uuid
from datetime import datetime, timezone

from project_analysis.stores.db import get_conn


class ProjectFileStore:
    def compute_content_hash(self, content: str) -> str:
        return hashlib.sha256((content or "").encode("utf-8")).hexdigest()

    def add(
        self,
        project_id: str,
        path: str,
        ext: str,
        size_bytes: int,
        content: str,
        content_hash: str | None = None,
    ) -> dict:
        file_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        resolved_hash = str(content_hash or self.compute_content_hash(content))

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_files
                (id, project_id, path, ext, size_bytes, content, content_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, project_id, path, ext, size_bytes, content, resolved_hash, now),
            )
            conn.commit()

        return {
            "id": file_id,
            "project_id": project_id,
            "path": path,
            "ext": ext,
            "size_bytes": size_bytes,
            "content": content,
            "content_hash": resolved_hash,
            "created_at": now,
        }

    def list_by_project(self, project_id: str) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, project_id, path, ext, size_bytes, content_hash, created_at
                FROM project_files
                WHERE project_id = ?
                ORDER BY path
                """,
                (project_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_full_by_project(self, project_id: str) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM project_files
                WHERE project_id = ?
                ORDER BY path
                """,
                (project_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_by_path(self, project_id: str, path: str) -> dict | None:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM project_files
                WHERE project_id = ? AND path = ?
                """,
                (project_id, path),
            ).fetchone()

        return dict(row) if row else None
