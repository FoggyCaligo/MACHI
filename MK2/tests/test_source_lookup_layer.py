import unittest
from unittest.mock import patch

from memory.retrieval.response_retriever import ResponseRetriever
from memory.retrieval.source_lookup_service import SourceLookupService
from prompts.response_builder import build_messages


class SourceLookupServiceTests(unittest.TestCase):
    def test_lookup_prefers_uploaded_source_excerpt_and_dedupes_source(self) -> None:
        service = SourceLookupService()

        uploaded_rows = [
            {
                "id": "upe-1",
                "source_id": "source-1",
                "source_file_path": "prefs.md",
                "topic": "explanation style",
                "topic_id": "topic-1",
                "candidate_content": "prefers structure-first explanations",
                "evidence_text": "The user prefers answers that start with the overall structure.",
                "created_at": "2026-04-14T10:00:00+00:00",
            },
            {
                "id": "upe-2",
                "source_id": "source-1",
                "source_file_path": "prefs.md",
                "topic": "explanation style",
                "topic_id": "topic-1",
                "candidate_content": "likes high-level framing before examples",
                "evidence_text": "Examples are better after the main frame is established.",
                "created_at": "2026-04-14T09:00:00+00:00",
            },
        ]
        chat_rows = [
            {
                "id": "chat-1",
                "topic": "explanation style",
                "topic_id": "topic-1",
                "candidate_content": "prefers structure-first explanations",
                "evidence_text": "The user reinforced that structure should come before examples.",
                "created_at": "2026-04-14T08:00:00+00:00",
            }
        ]
        project_rows = [
            {
                "id": "project-1",
                "project_id": "project-77",
                "source_file_path": "docs/profile-notes.md",
                "topic": "work style",
                "topic_id": "topic-3",
                "candidate_content": "likes incremental iteration",
                "evidence_text": "Project evidence suggests the user prefers incremental refinement.",
                "created_at": "2026-04-14T07:00:00+00:00",
            }
        ]

        with patch.object(service.uploaded_evidence_store, "list_profile_evidence", return_value=uploaded_rows):
            with patch.object(service.chat_evidence_store, "list_profile_evidence", return_value=chat_rows):
                with patch.object(service.project_evidence_store, "list_profile_evidence", return_value=project_rows):
                    with patch.object(
                        service.uploaded_source_store,
                        "get",
                        return_value={
                            "id": "source-1",
                            "filename": "prefs.md",
                            "content": "Start with the big picture.\n\nThen move into examples.",
                            "created_at": "2026-04-14T10:00:00+00:00",
                        },
                    ):
                        with patch.object(
                            service.passage_selector,
                            "select_followup_passages",
                            return_value=(
                                [
                                    {
                                        "filename": "prefs.md",
                                        "passage_index": 1,
                                        "text": "Start with the big picture before diving into examples.",
                                    }
                                ],
                                {"selection_mode": "followup_passage_embedding_similarity"},
                                ),
                            ):
                                with patch.object(
                                    service.profile_graph,
                                    "same_meaning",
                                    side_effect=lambda left, right, **kwargs: " ".join((left or "").split()).lower()
                                    == " ".join((right or "").split()).lower(),
                                ):
                                    with patch("memory.retrieval.source_lookup_service.embed_text", return_value=[1.0, 0.0]):
                                        with patch(
                                            "memory.retrieval.source_lookup_service.embed_texts",
                                            return_value=[[1.0, 0.0], [0.95, 0.05], [0.75, 0.25], [0.55, 0.45]],
                                        ):
                                            with patch(
                                                "memory.retrieval.source_lookup_service.cosine_similarity",
                                                side_effect=[0.92, 0.88, 0.76, 0.61],
                                            ):
                                                result = service.lookup(
                                                    "Should you explain things with structure first?",
                                                    active_topic_id="topic-1",
                                                )

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["source_kind"], "uploaded_profile_source")
        self.assertEqual(result[0]["label"], "prefs.md")
        self.assertIn("big picture", result[0]["excerpt"])
        self.assertEqual(result[0]["trace"]["topic_anchor"], "explanation style")
        self.assertTrue(result[0]["trace"]["active_topic_match"])
        self.assertEqual(result[0]["trace"]["topic_support_count"], 2)
        self.assertEqual(result[0]["trace"]["candidate_support_count"], 2)
        self.assertEqual(result[0]["trace"]["connections"][0]["label"], "chat_profile_evidence")
        self.assertEqual(result[0]["trace"]["connections"][0]["via"], ["same_topic", "same_candidate_meaning"])
        self.assertEqual(
            sum(1 for item in result if item["source_kind"] == "uploaded_profile_source"),
            1,
        )
        self.assertEqual(result[1]["source_kind"], "chat_profile_evidence")
        self.assertEqual(result[2]["source_kind"], "project_profile_evidence")

    def test_lookup_falls_back_to_recent_uploaded_source(self) -> None:
        service = SourceLookupService()

        with patch.object(service.uploaded_evidence_store, "list_profile_evidence", return_value=[]):
            with patch.object(service.chat_evidence_store, "list_profile_evidence", return_value=[]):
                with patch.object(service.project_evidence_store, "list_profile_evidence", return_value=[]):
                    with patch.object(service.state_store, "get_state", return_value={"value": "source-2"}):
                        with patch.object(
                            service.uploaded_source_store,
                            "get",
                            return_value={
                                "id": "source-2",
                                "filename": "recent-notes.md",
                                "content": "The user likes concise summaries first.\n\nDetails can follow after.",
                                "created_at": "2026-04-14T11:00:00+00:00",
                            },
                        ):
                            with patch.object(
                                service.passage_selector,
                                "select_followup_passages",
                                return_value=(
                                    [
                                        {
                                            "filename": "recent-notes.md",
                                            "passage_index": 1,
                                            "text": "The user likes concise summaries first.",
                                        }
                                    ],
                                    {"selection_mode": "followup_passage_embedding_similarity"},
                                ),
                            ):
                                result = service.lookup("How should you summarize things?")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_kind"], "uploaded_profile_source")
        self.assertEqual(result[0]["label"], "recent-notes.md")
        self.assertIn("concise summaries first", result[0]["excerpt"])


class ResponseRetrieverSourceLookupTests(unittest.TestCase):
    def test_retrieve_includes_recent_sources_context(self) -> None:
        retriever = ResponseRetriever()

        with patch.object(retriever.state_store, "get_active_topic_id", return_value="topic-1"):
            with patch.object(retriever.profile_store, "get_active_by_topic", return_value=None):
                with patch.object(retriever.correction_store, "list_active_by_topic", return_value=[]):
                    with patch.object(retriever.summary_store, "get_by_topic", return_value=None):
                        with patch.object(retriever.candidate_profile_store, "list_active_by_topic", return_value=[]):
                            with patch.object(retriever.correction_store, "list_active", return_value=[]):
                                with patch.object(retriever.episode_store, "find_relevant", return_value=[]):
                                    with patch.object(retriever.raw_message_store, "recent", return_value=[]):
                                        with patch.object(retriever.state_store, "get_all", return_value=[]):
                                            with patch.object(
                                                retriever.source_lookup_service,
                                                "lookup",
                                                return_value=[
                                                    {
                                                        "source_kind": "uploaded_profile_source",
                                                        "label": "prefs.md",
                                                        "excerpt": "Start with the structure first.",
                                                    }
                                                ],
                                            ) as mocked_lookup:
                                                result = retriever.retrieve("How do I prefer explanations?")

        self.assertEqual(result["recent_sources"][0]["label"], "prefs.md")
        mocked_lookup.assert_called_once_with(
            "How do I prefer explanations?",
            limit=3,
            active_topic_id="topic-1",
        )


class ResponseBuilderSourceRenderingTests(unittest.TestCase):
    def test_build_messages_adds_answering_hint_when_reference_context_exists(self) -> None:
        messages = build_messages(
            "Do you remember how I prefer explanations?",
            {
                "profiles": [
                    {
                        "topic": "explanation style",
                        "content": "prefers structure-first explanations",
                    }
                ]
            },
        )

        content = messages[1]["content"]
        self.assertIn("[Answering Hint]", content)
        self.assertIn("currently available conversation/memory context", content)
        self.assertIn("Do not default to generic disclaimers", content)

    def test_build_messages_renders_recent_sources_as_reference_only(self) -> None:
        messages = build_messages(
            "Answer with my preferred explanation style.",
            {
                "recent_sources": [
                    {
                        "source_kind": "uploaded_profile_source",
                        "label": "prefs.md",
                        "topic": "explanation style",
                        "excerpt": "Start with the overall structure before examples.",
                        "candidate_content": "prefers structure-first explanations",
                        "trace": {
                            "topic_anchor": "explanation style",
                            "active_topic_match": True,
                            "topic_support_count": 2,
                            "candidate_support_count": 2,
                            "connections": [
                                {
                                    "label": "chat_profile_evidence",
                                    "via": ["same_topic", "same_candidate_meaning"],
                                    "candidate_content": "prefers structure-first explanations",
                                }
                            ],
                        },
                    }
                ]
            },
        )

        content = messages[1]["content"]
        self.assertIn("[Reference Sources]", content)
        self.assertIn("reference only; use when helpful, not as a hard constraint", content)
        self.assertIn("prefs.md | explanation style | uploaded_profile_source", content)
        self.assertIn("Start with the overall structure before examples.", content)
        self.assertIn("related_candidate: prefers structure-first explanations", content)
        self.assertIn("source_trace: topic=explanation style | active_topic_match=yes | topic_support=2 | candidate_support=2", content)
        self.assertIn("linked_source: chat_profile_evidence | same_topic,same_candidate_meaning | candidate=prefers structure-first explanations", content)


if __name__ == "__main__":
    unittest.main()
