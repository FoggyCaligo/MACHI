import uuid
from datetime import datetime, timezone

from project_analysis.stores.db import get_conn


class ProjectStore:
    def create(self, name: str, zip_path: str, status: str = "uploaded") -> dict:
        project_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, zip_path, created_at, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, name, zip_path, now, status),
            )
            conn.commit()

        return {
            "id": project_id,
            "name": name,
            "zip_path": zip_path,
            "created_at": now,
            "status": status,
        }

    def get(self, project_id: str) -> dict | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()

        return dict(row) if row else None

    def update_status(self, project_id: str, status: str) -> None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE projects SET status = ? WHERE id = ?",
                (status, project_id),
            )
            conn.commit()