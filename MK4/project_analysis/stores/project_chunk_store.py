import json
import uuid
from datetime import datetime, timezone

from project_analysis.stores.db import get_conn
from tools.text_embedding import embed_text


class ProjectChunkStore:
    def _decode_embedding(self, raw: str | None) -> list[float]:
        if not raw:
            return []
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(values, list):
            return []
        return [float(v) for v in values]

    def _encode_embedding(self, embedding: list[float] | None) -> str:
        return json.dumps(embedding or [], ensure_ascii=False)

    def _hydrate_row(self, row) -> dict:
        chunk = dict(row)
        chunk["embedding"] = self._decode_embedding(chunk.get("embedding_json"))
        return chunk

    def add(
        self,
        project_id: str,
        file_id: str,
        chunk_index: int,
        start_line: int,
        end_line: int,
        content: str,
        summary: str | None = None,
        embedding: list[float] | None = None,
    ) -> dict:
        chunk_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        resolved_embedding = embedding or embed_text(content, kind="passage")

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO project_chunks
                (id, project_id, file_id, chunk_index, start_line, end_line,
                 content, summary, embedding_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    self._encode_embedding(resolved_embedding),
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
            "embedding_json": self._encode_embedding(resolved_embedding),
            "embedding": resolved_embedding,
            "created_at": now,
        }

    def update_embedding(self, chunk_id: str, embedding: list[float] | None) -> None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE project_chunks SET embedding_json = ? WHERE id = ?",
                (self._encode_embedding(embedding), chunk_id),
            )
            conn.commit()

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
        return [self._hydrate_row(row) for row in rows]

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
        return [self._hydrate_row(row) for row in rows]

    def get_by_ids(self, chunk_ids: list[str]) -> list[dict]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM project_chunks WHERE id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
        return [self._hydrate_row(row) for row in rows]
