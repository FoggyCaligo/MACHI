import unittest
from unittest.mock import patch

from memory.services.memory_apply_service import MemoryApplyService
from project_analysis.services.project_ask_service import ProjectAskService
from project_analysis.services.project_profile_evidence_service import ProjectProfileEvidenceService


class MemoryApplyServiceCorrectionScopeTests(unittest.TestCase):
    def test_conflicting_profile_correction_is_checked_within_topic_scope(self) -> None:
        service = MemoryApplyService()

        correction_rows = [
            {
                "reason": "profile:explicit_correction",
                "content": "사용자는 구조적 설명을 선호한다",
                "supersedes_profile_id": "",
            }
        ]

        with patch.object(service.correction_store, "list_active_by_topic", return_value=correction_rows) as mocked_by_topic:
            with patch.object(service.correction_store, "list_active") as mocked_global:
                with patch.object(service, "_same_meaning", return_value=True):
                    conflicted = service._has_conflicting_active_correction(
                        "구조적 설명을 좋아함",
                        topic="설명 선호",
                        topic_id="topic-1",
                    )

        self.assertTrue(conflicted)
        mocked_by_topic.assert_called_once_with(topic="설명 선호", topic_id="topic-1", limit=20)
        mocked_global.assert_not_called()


class ProjectProfileEvidenceServiceIncrementalTests(unittest.TestCase):
    def test_ensure_extracted_reuses_existing_evidence_without_reextract(self) -> None:
        service = ProjectProfileEvidenceService()
        docs = [
            {"path": "docs/a.md", "content": "A", "content_hash": "hash-a"},
            {"path": "docs/b.md", "content": "B", "content_hash": "hash-b"},
        ]
        evidences = [
            {"source_file_path": "docs/a.md", "source_file_paths": ["docs/a.md"], "source_file_hashes": {"docs/a.md": "hash-a"}},
            {"source_file_path": "docs/b.md", "source_file_paths": ["docs/b.md"], "source_file_hashes": {"docs/b.md": "hash-b"}},
        ]

        with patch.object(service, "_select_documents", return_value=docs):
            with patch.object(service.evidence_store, "list_by_project_paths", return_value=evidences):
                with patch.object(service, "extract_and_store") as mocked_extract:
                    result = service.ensure_extracted("project-1")

        self.assertTrue(result["reused"])
        self.assertFalse(result["stored"])
        self.assertFalse(result["needs_memory_sync"])
        mocked_extract.assert_not_called()

    def test_ensure_extracted_extracts_only_missing_paths(self) -> None:
        service = ProjectProfileEvidenceService()
        docs = [
            {"path": "docs/a.md", "content": "A", "content_hash": "hash-a"},
            {"path": "docs/b.md", "content": "B", "content_hash": "hash-b"},
        ]
        existing_evidences = [
            {"source_file_path": "docs/a.md", "source_file_paths": ["docs/a.md"], "source_file_hashes": {"docs/a.md": "hash-a"}},
        ]

        with patch.object(service, "_select_documents", return_value=docs):
            with patch.object(service.evidence_store, "list_by_project_paths", return_value=existing_evidences):
                with patch.object(
                    service,
                    "extract_and_store",
                    return_value={"stored": True, "source_files": ["docs/b.md"], "needs_memory_sync": True},
                ) as mocked_extract:
                    result = service.ensure_extracted("project-1", model="gemma3:4b")

        self.assertTrue(result["stored"])
        mocked_extract.assert_called_once_with(
            "project-1",
            model="gemma3:4b",
            source_paths=["docs/b.md"],
            force_refresh=False,
        )

    def test_ensure_extracted_reextracts_stale_paths_when_file_hash_changed(self) -> None:
        service = ProjectProfileEvidenceService()
        docs = [
            {"path": "docs/a.md", "content": "A-new", "content_hash": "hash-a-new"},
            {"path": "docs/b.md", "content": "B", "content_hash": "hash-b"},
        ]
        existing_evidences = [
            {"source_file_path": "docs/a.md", "source_file_paths": ["docs/a.md"], "source_file_hashes": {"docs/a.md": "hash-a-old"}},
            {"source_file_path": "docs/b.md", "source_file_paths": ["docs/b.md"], "source_file_hashes": {"docs/b.md": "hash-b"}},
        ]

        with patch.object(service, "_select_documents", return_value=docs):
            with patch.object(service.evidence_store, "list_by_project_paths", return_value=existing_evidences):
                with patch.object(
                    service,
                    "extract_and_store",
                    return_value={"stored": True, "source_files": ["docs/a.md"], "needs_memory_sync": True},
                ) as mocked_extract:
                    result = service.ensure_extracted("project-1", model="gemma3:4b")

        self.assertTrue(result["stored"])
        mocked_extract.assert_called_once_with(
            "project-1",
            model="gemma3:4b",
            source_paths=["docs/a.md"],
            force_refresh=False,
        )

    def test_extract_and_store_deletes_only_selected_paths_and_persists_hashes(self) -> None:
        service = ProjectProfileEvidenceService()
        docs = [{"path": "docs/a.md", "content": "A", "content_hash": "hash-a"}]
        candidates = [
            {
                "topic": "설명 선호",
                "candidate_content": "구조적 설명을 선호함",
                "source_strength": "explicit_self_statement",
                "confidence": 0.9,
                "evidence_text": "근거",
                "direct_confirm": False,
                "source_file_paths": ["docs/a.md"],
            }
        ]
        envelopes = [
            {
                "kind": "profile_candidate",
                "topic": "설명 선호",
                "content": "구조적 설명을 선호함",
                "source_strength": "explicit_self_statement",
                "confidence": 0.9,
                "metadata": {
                    "evidence_text": "근거",
                    "source_file_paths": ["docs/a.md"],
                    "memory_tier": "candidate",
                    "direct_confirm": False,
                },
            }
        ]

        with patch.object(service, "_select_documents", return_value=docs):
            with patch.object(service.evidence_store, "delete_by_project_paths", return_value=2) as mocked_delete_paths:
                with patch.object(service.extraction_service, "run_extract", return_value=type("R", (), {"text": "[]"})()):
                    with patch.object(service, "_extract_json_array", return_value=candidates):
                        with patch.object(service, "_resolve_candidate_topic", side_effect=lambda candidate, model=None: candidate):
                            with patch.object(service.normalizer, "normalize_profile_candidate_envelopes", return_value=envelopes):
                                with patch.object(service.memory_ingress, "persist_profile_candidate_envelopes", return_value=[]) as mocked_persist:
                                    service.extract_and_store("project-1", source_paths=["docs/a.md"], force_refresh=True)

        mocked_delete_paths.assert_called_once_with("project-1", ["docs/a.md"])
        mocked_persist.assert_called_once_with(
            channel="project_artifact",
            owner_id="project-1",
            evidence_envelopes=envelopes,
            source_file_hash_by_path={"docs/a.md": "hash-a"},
        )


class ProjectAskServiceIncrementalTests(unittest.TestCase):
    def test_profile_question_reuses_existing_evidence_without_sync(self) -> None:
        service = ProjectAskService()

        with patch.object(service.profile_route_resolver, "resolve", return_value="profile_question"):
            with patch.object(
                service.profile_evidence_service,
                "ensure_extracted",
                return_value={
                    "stored": False,
                    "reused": True,
                    "needs_memory_sync": False,
                },
            ) as mocked_ensure:
                with patch.object(
                    service.profile_evidence_service,
                    "answer_from_project",
                    return_value={"answer": "프로필 답변", "used_profile_evidence": []},
                ) as mocked_answer:
                    with patch.object(service.memory_ingress_service, "sync_project") as mocked_sync:
                        with patch.object(service.project_review_store, "add"):
                            result = service.ask("project-1", "이 프로젝트로 본 내 성향은?", model="gemma3:4b")

        self.assertEqual(result["answer"], "프로필 답변")
        mocked_ensure.assert_called_once_with("project-1", model="gemma3:4b")
        mocked_answer.assert_called_once()
        mocked_sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
