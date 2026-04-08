import uuid
from datetime import datetime, timezone

from project_analysis.stores.db import get_conn


class UploadedProfileSourceStore:
    def add(
        self,
        filename: str,
        content: str,
        user_request: str | None = None,
    ) -> dict:
        source_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO uploaded_profile_sources (
                    id,
                    filename,
                    content,
                    user_request,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_id, filename, content, user_request, now),
            )
            conn.commit()

        return {
            "id": source_id,
            "filename": filename,
            "content": content,
            "user_request": user_request,
            "created_at": now,
        }

    def get(self, source_id: str) -> dict | None:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM uploaded_profile_sources
                WHERE id = ?
                """,
                (source_id,),
            ).fetchone()

        return dict(row) if row else None
