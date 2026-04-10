from project_analysis.stores.project_chunk_store import ProjectChunkStore
from project_analysis.stores.project_file_store import ProjectFileStore
from tools.text_embedding import cosine_similarity, embed_text, embed_texts


class ProjectRetriever:
    def __init__(self) -> None:
        self.project_file_store = ProjectFileStore()
        self.project_chunk_store = ProjectChunkStore()

    def _backfill_missing_embeddings(self, chunks: list[dict]) -> None:
        missing_chunks = [
            chunk
            for chunk in chunks
            if not chunk.get("embedding") and (chunk.get("content") or "").strip()
        ]
        if not missing_chunks:
            return

        embeddings = embed_texts([chunk["content"] for chunk in missing_chunks], kind="passage")
        for chunk, embedding in zip(missing_chunks, embeddings):
            chunk["embedding"] = embedding
            self.project_chunk_store.update_embedding(chunk["id"], embedding)

    def retrieve(self, project_id: str, question: str, top_k: int = 5) -> list[dict]:
        query_embedding = embed_text(question, kind="query")
        if not query_embedding:
            return []

        files = self.project_file_store.list_by_project(project_id)
        file_map = {file_info["id"]: file_info for file_info in files}
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

        scored.sort(key=lambda item: (-item["score"], item["file_path"], item["chunk_index"]))
        return scored[:top_k]
