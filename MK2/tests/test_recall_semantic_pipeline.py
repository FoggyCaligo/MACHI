import unittest
from unittest.mock import patch

from memory.retrieval.recall_retriever import RecallRetriever
from memory.stores.raw_message_store import RawMessageStore


class RecallRetrieverSemanticRouteTests(unittest.TestCase):
    def test_retrieve_uses_semantic_row_ranking_instead_of_store_search(self) -> None:
        retriever = RecallRetriever()

        episodes = [
            {
                "id": "episode-1",
                "topic": "설명 선호",
                "topic_id": "topic-1",
                "summary": "사용자는 구조적으로 설명받는 것을 선호했다",
                "raw_ref": "구조부터 설명해달라고 요청했다",
                "created_at": "2026-04-14T00:00:00+00:00",
                "last_referenced_at": "2026-04-14T00:00:00+00:00",
                "state": "active",
            }
        ]
        profiles = [
            {
                "id": "profile-1",
                "topic": "설명 선호",
                "topic_summary": "설명 선호",
                "content": "구조적 설명을 선호한다",
                "updated_at": "2026-04-14T00:00:00+00:00",
                "status": "active",
            }
        ]
        corrections = [
            {
                "id": "correction-1",
                "topic": "설명 선호",
                "topic_summary": "설명 선호",
                "content": "예시보다 구조를 먼저 설명해달라",
                "created_at": "2026-04-14T00:00:00+00:00",
                "status": "active",
            }
        ]
        summaries = [
            {
                "id": "summary-1",
                "topic": "설명 선호",
                "topic_summary": "설명 선호",
                "content": "사용자는 설명을 들을 때 전체 구조를 먼저 잡는 편을 선호한다",
                "updated_at": "2026-04-14T00:00:00+00:00",
            }
        ]

        with patch.object(retriever.episode_store, "find_relevant", return_value=episodes):
            with patch.object(retriever.episode_store, "reference") as mocked_reference:
                with patch.object(
                    retriever.topic_store,
                    "find_similar_topics",
                    return_value=[{"id": "topic-1", "name": "설명 선호", "summary": "설명 선호", "similarity": 0.82}],
                ):
                    with patch.object(
                        retriever.topic_store,
                        "list_active_topics",
                        return_value=[{"id": "topic-1", "name": "설명 선호", "summary": "설명 선호"}],
                    ):
                        with patch.object(retriever.summary_store, "get_by_topic", side_effect=[summaries[0], None]):
                            with patch.object(retriever.profile_store, "get_active_profiles", return_value=profiles):
                                with patch.object(retriever.correction_store, "list_active", return_value=corrections):
                                    with patch.object(retriever.raw_message_store, "search_with_context", return_value=[]):
                                        with patch.object(retriever.profile_store, "search", side_effect=AssertionError("legacy search should not be used")):
                                            with patch.object(retriever.correction_store, "search", side_effect=AssertionError("legacy search should not be used")):
                                                with patch.object(retriever.summary_store, "search", side_effect=AssertionError("legacy search should not be used")):
                                                    with patch.object(
                                                        retriever,
                                                        "_rank_rows_by_query",
                                                        side_effect=[profiles, corrections, summaries],
                                                    ) as mocked_rank:
                                                        result = retriever.retrieve("내가 구조적으로 설명해달라고 했던 적 있어?")

        self.assertTrue(result["found"])
        self.assertEqual(mocked_rank.call_count, 3)
        self.assertEqual(result["trace"]["topics"][0]["id"], "topic-1")
        self.assertEqual(result["trace"]["profiles"][0]["topic"], "설명 선호")
        self.assertEqual(result["trace"]["corrections"][0]["topic"], "설명 선호")
        self.assertEqual(result["trace"]["summaries"][0]["topic"], "설명 선호")
        mocked_reference.assert_called_once_with("episode-1")


class RawMessageStoreSemanticSearchTests(unittest.TestCase):
    def test_search_with_context_uses_semantic_similarity(self) -> None:
        store = RawMessageStore()
        messages = [
            {
                "id": "m1",
                "role": "user",
                "content": "구조적으로 설명해달라고 했어",
                "created_at": "2026-04-14T00:00:00+00:00",
                "episode_id": None,
            },
            {
                "id": "m2",
                "role": "assistant",
                "content": "예시를 먼저 들었지",
                "created_at": "2026-04-14T00:01:00+00:00",
                "episode_id": None,
            },
            {
                "id": "m3",
                "role": "user",
                "content": "전체 구조를 먼저 잡는 설명을 더 좋아해",
                "created_at": "2026-04-14T00:02:00+00:00",
                "episode_id": None,
            },
        ]

        with patch.object(store, "_load_recent_messages", return_value=messages):
            with patch("memory.stores.raw_message_store.embed_text", return_value=[1.0, 0.0]):
                with patch(
                    "memory.stores.raw_message_store.embed_texts",
                    return_value=[[1.0, 0.0], [0.0, 1.0], [0.8, 0.2]],
                ):
                    with patch(
                        "memory.stores.raw_message_store.cosine_similarity",
                        side_effect=[0.93, 0.14, 0.72],
                    ):
                        results = store.search_with_context(
                            "구조를 먼저 설명하는 걸 좋아했나?",
                            limit=2,
                            before=1,
                            after=1,
                        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["match_type"], "semantic_query")
        self.assertEqual(results[0]["anchor_message"]["id"], "m1")
        self.assertEqual(results[1]["anchor_message"]["id"], "m3")
        self.assertEqual(results[0]["matched_terms"], [])


if __name__ == "__main__":
    unittest.main()
