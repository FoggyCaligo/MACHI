from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK4.app.pipeline import _ensure_participant_anchors
from MK4.core.storage.db import close_db, open_db
from MK4.core.storage.world_graph import get_node


class UserIdMemoryScopeTest(unittest.TestCase):
    def test_user_anchor_persists_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            conn = open_db(str(db_path))
            try:
                first = _ensure_participant_anchors(conn, "session-a", "user-123")
                second = _ensure_participant_anchors(conn, "session-b", "user-123")

                self.assertEqual(first["user"], second["user"])
                self.assertNotEqual(first["assistant"], second["assistant"])
                self.assertNotEqual(first["search"], second["search"])

                user_node = get_node(conn, first["user"])
                self.assertIsNotNone(user_node)
                self.assertEqual(user_node.payload.get("memory_scope"), "user_id")
                self.assertEqual(user_node.payload.get("user_id"), "user-123")
                self.assertIsNone(user_node.payload.get("session_id"))
            finally:
                close_db(conn)

    def test_different_users_get_different_user_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            conn = open_db(str(db_path))
            try:
                first = _ensure_participant_anchors(conn, "shared-session", "user-a")
                second = _ensure_participant_anchors(conn, "shared-session", "user-b")

                self.assertNotEqual(first["user"], second["user"])
                self.assertEqual(first["assistant"], second["assistant"])
                self.assertEqual(first["search"], second["search"])
            finally:
                close_db(conn)


if __name__ == "__main__":
    unittest.main()

