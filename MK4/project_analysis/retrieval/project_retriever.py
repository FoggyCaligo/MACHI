from __future__ import annotations

import struct

from project_analysis.stores.project_chunk_store import ProjectChunkStore
from project_analysis.stores.project_file_store import ProjectFileStore
from tools.text_embedding import embed_text, embed_texts


def _encode_vec(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


class ProjectRetriever:
    def __init__(self) -> None:
        self.project_file_store = ProjectFileStore()
        self.project_chunk_store = ProjectChunkStore()

    def _backfill_missing_embeddings(self, chunks: list[dict]) -> None:
        missing = [c for c in chunks if not c.get("embedding") and (c.get("content") or "").strip()]
        if not missing:
            return
        embeddings = embed_texts([c["content"] for c in missing], kind="passage")
        for chunk, embedding in zip(missing, embeddings):
            chunk["embedding"] = embedding
            self.project_chunk_store.update_embedding(chunk["id"], embedding)

    def _retrieve_via_vec(self, project_id: str, question: str, top_k: int) -> list[dict] | None:
        """
        sqlite-vec ANN 검색.
        실패하면 None을 반환해 fallback을 유도한다.
        """
        from project_analysis.stores.db import get_conn

        query_embedding = embed_text(question, kind="query")
        if not query_embedding:
            return None

        try:
            with get_conn() as conn:
                # vec_project_chunks에서 ANN top_k * 3 후보를 뽑고
                # project_chunks JOIN으로 project_id 필터링
                candidates = conn.execute(
                    """
                    SELECT
                        pc.id         AS chunk_id,
                        pc.project_id,
                        pc.file_id,
                        pc.chunk_index,
                        pc.start_line,
                        pc.end_line,
                        pc.content,
                        v.distance
                    FROM vec_project_chunks v
                    JOIN project_chunks pc ON pc.id = v.chunk_id
                    WHERE v.embedding MATCH ?
                      AND pc.project_id = ?
                      AND k = ?
                    ORDER BY v.distance
                    """,
                    (_encode_vec(query_embedding), project_id, top_k * 3),
                ).fetchall()
        except Exception as exc:
            print(f"[RETRIEVER][WARN] vec search failed, falling back: {exc}", flush=True)
            return None

        if not candidates:
            return None

        files = self.project_file_store.list_by_project(project_id)
        file_map = {f["id"]: f for f in files}

        results: list[dict] = []
        for row in candidates:
            file_info = file_map.get(row["file_id"])
            if not file_info:
                continue
            content = (row["content"] or "").strip()
            if not content:
                continue
            # distance → similarity (vec0 L2 distance를 score로 근사 변환)
            distance = float(row["distance"])
            score = 1.0 / (1.0 + distance)
            results.append(
                {
                    "file_id": file_info["id"],
                    "file_path": file_info["path"],
                    "chunk_id": row["chunk_id"],
                    "chunk_index": row["chunk_index"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "content": content,
                    "score": score,
                }
            )
            if len(results) >= top_k:
                break

        return results

    def _retrieve_via_cosine(self, project_id: str, question: str, top_k: int) -> list[dict]:
        """Python-side cosine fallback (기존 방식)."""
        from tools.text_embedding import cosine_similarity

        query_embedding = embed_text(question, kind="query")
        if not query_embedding:
            return []

        files = self.project_file_store.list_by_project(project_id)
        file_map = {f["id"]: f for f in files}
        chunks = self.project_chunk_store.list_by_project(project_id)
        self._backfill_missing_embeddings(chunks)

        scored: list[dict] = []
        for chunk in chunks:
            file_info = file_map.get(chunk["file_id"])
            if not file_info:
                continue
            content = (chunk.get("content") or "").strip()
            if not content:
                continue
            similarity = cosine_similarity(query_embedding, chunk.get("embedding") or [])
            if similarity <= 0.0:
                continue
            scored.append(
                {
                    "file_id": file_info["id"],
                    "file_path": file_info["path"],
                    "chunk_id": chunk["id"],
                    "chunk_index": chunk["chunk_index"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                    "content": content,
                    "score": similarity,
                }
            )

        scored.sort(key=lambda x: (-x["score"], x["file_path"], x["chunk_index"]))
        return scored[:top_k]

    def retrieve(self, project_id: str, question: str, top_k: int = 5) -> list[dict]:
        # 1차: sqlite-vec ANN
        results = self._retrieve_via_vec(project_id, question, top_k)
        if results is not None:
            return results
        # 2차: cosine fallback (vec 테이블이 아직 비어있거나 실패한 경우)
        return self._retrieve_via_cosine(project_id, question, top_k)