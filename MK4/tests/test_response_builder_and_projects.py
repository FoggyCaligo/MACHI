import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from project_analysis.stores import db as project_db
from project_analysis.stores.project_store import ProjectStore
from prompts.response_builder import build_messages


class ResponseBuilderTests(unittest.TestCase):
    def test_build_messages_always_wraps_current_user_request(self) -> None:
        messages = build_messages("안녕", {})

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "[현재 사용자 요청]\n안녕")

    def test_recent_messages_are_rendered_as_role_lines(self) -> None:
        messages = build_messages(
            "이어서 말해줘",
            {
                "recent_messages": [
                    {"role": "user", "content": "안녕"},
                    {"role": "assistant", "content": "반가워"},
                ]
            },
        )

        content = messages[1]["content"]
        self.assertIn("[최근 대화 맥락]", content)
        self.assertIn("- user: 안녕", content)
        self.assertIn("- assistant: 반가워", content)
        self.assertIn("[현재 사용자 요청]\n이어서 말해줘", content)




    def test_candidate_profiles_are_rendered_as_candidate_section(self) -> None:
        messages = build_messages(
            "이어서 말해줘",
            {
                "profiles": [{"topic": "설명 선호", "content": "구조적 설명을 선호함"}],
                "candidate_profiles": [{"topic": "설명 선호", "content": "예시보다 구조를 더 선호함"}],
            },
        )

        content = messages[1]["content"]
        self.assertIn("[사용자 프로필 후보]", content)
        self.assertIn("예시보다 구조를 더 선호함", content)


class ProjectStoreTests(unittest.TestCase):
    def test_list_recent_returns_latest_projects_first(self) -> None:
        temp_dir = Path.cwd() / "data" / "tmp_project_store_test"
        temp_db_path = temp_dir / "memory.db"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with patch.object(project_db, "DATA_DIR", temp_dir):
                with patch.object(project_db, "DB_PATH", temp_db_path):
                    with patch("project_analysis.stores.project_store.get_conn", project_db.get_conn):
                        project_db.init_project_tables()
                        store = ProjectStore()
                        first = store.create(name="첫 프로젝트", zip_path="first.zip")
                        second = store.create(name="둘째 프로젝트", zip_path="second.zip")

                        projects = store.list_recent(limit=10)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(projects[0]["id"], second["id"])
        self.assertEqual(projects[0]["name"], "둘째 프로젝트")
        self.assertEqual(projects[1]["id"], first["id"])


if __name__ == "__main__":
    unittest.main()
