import uuid
from datetime import datetime, timezone

from project_analysis.stores.db import get_conn

class ProjectChunkStore:
    def add(
        self,
        project_id: str,
        file_id: str,
        chunk_index: int,
        start_line: int,
        end_line: int,
        content: str,
        summary: str | None = None,
    ) -> dict:
        chunk_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_chunks
                (id, project_id, file_id, chunk_index, start_line, end_line, content, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    project_id,
                    file_id,
                    chunk_index,
                    start_line,
                    end_line,
                    content,
                    summary,
                    now,
                ),
            )
            conn.commit()

        return {
            "id": chunk_id,
            "project_id": project_id,
            "file_id": file_id,
            "chunk_index": chunk_index,
            "start_line": start_line,
            "end_line": end_line,
            "content": content,
            "summary": summary,
            "created_at": now,
        }

    def list_by_project(self, project_id: str) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM project_chunks
                WHERE project_id = ?
                ORDER BY file_id, chunk_index
                """,
                (project_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_by_file(self, file_id: str) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM project_chunks
                WHERE file_id = ?
                ORDER BY chunk_index
                """,
                (file_id,),
            ).fetchall()

        return [dict(row) for row in rows]