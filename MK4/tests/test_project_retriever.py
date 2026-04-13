import unittest
from pathlib import Path
import shutil
from unittest.mock import patch

from project_analysis.retrieval.project_retriever import ProjectRetriever
from project_analysis.stores import db as project_db


class ProjectDbTests(unittest.TestCase):
    def test_init_project_tables_creates_core_tables_without_vec_extension(self) -> None:
        temp_dir = Path.cwd() / "data" / "tmp_project_db_test"
        temp_db_path = temp_dir / "memory.db"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with patch.object(project_db, "DATA_DIR", temp_dir):
                with patch.object(project_db, "DB_PATH", temp_db_path):
                    project_db.init_project_tables()

                    with project_db.get_conn() as conn:
                        rows = conn.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        ).fetchall()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        table_names = {row["name"] for row in rows}

        self.assertTrue(
            {
                "projects",
                "project_files",
                "project_chunks",
                "project_reviews",
                "project_profile_evidence",
                "uploaded_profile_sources",
                "uploaded_profile_evidence",
            }.issubset(table_names)
        )
        self.assertNotIn("vec_project_chunks", table_names)


class ProjectRetrieverTests(unittest.TestCase):
    def test_retrieve_uses_python_cosine_and_backfills_missing_embeddings(self) -> None:
        retriever = ProjectRetriever()
        files = [
            {"id": "file-1", "path": "src/app.py"},
        ]
        chunks = [
            {
                "id": "chunk-1",
                "file_id": "file-1",
                "chunk_index": 0,
                "start_line": 1,
                "end_line": 10,
                "content": "first chunk",
                "embedding": [],
            },
            {
                "id": "chunk-2",
                "file_id": "file-1",
                "chunk_index": 1,
                "start_line": 11,
                "end_line": 20,
                "content": "second chunk",
                "embedding": [0.0, 1.0],
            },
        ]

        with patch.object(retriever.project_file_store, "list_by_project", return_value=files):
            with patch.object(retriever.project_chunk_store, "list_by_project", return_value=chunks):
                with patch.object(retriever.project_chunk_store, "update_embedding") as mocked_update:
                    with patch(
                        "project_analysis.retrieval.project_retriever.embed_text",
                        return_value=[1.0, 0.0],
                    ):
                        with patch(
                            "project_analysis.retrieval.project_retriever.embed_texts",
                            return_value=[[1.0, 0.0]],
                        ):
                            with patch(
                                "tools.text_embedding.cosine_similarity",
                                side_effect=[0.95, 0.35],
                            ):
                                results = retriever.retrieve("project-1", "where is the app entry?", top_k=2)

        self.assertEqual([item["chunk_id"] for item in results], ["chunk-1", "chunk-2"])
        self.assertEqual(results[0]["file_path"], "src/app.py")
        mocked_update.assert_called_once_with("chunk-1", [1.0, 0.0])


if __name__ == "__main__":
    unittest.main()
