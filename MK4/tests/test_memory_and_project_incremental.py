import unittest
from unittest.mock import patch

from config import PROFILE_SEMANTIC_CLUSTER_THRESHOLD
from memory.policies.memory_classification_policy import (
    MemoryClassificationPolicy,
    SOURCE_STRENGTH_ORDER,
)
from memory.services.profile_evidence_graph import ProfileEvidenceGraph
from memory.services.memory_apply_service import MemoryApplyService
from memory.services.memory_ingress_service import MemoryIngressService
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


class MemoryApplyServiceDemotionTests(unittest.TestCase):
    def test_reconcile_topics_demotes_confirmed_profile_below_threshold(self) -> None:
        service = MemoryApplyService()
        active_profile = {
            "id": "profile-1",
            "topic_id": "topic-1",
            "topic": "설명 선호",
            "content": "구조적 설명을 선호한다",
            "confidence": 0.82,
            "source": "evidence_promotion:explicit_self_statement",
        }

        with patch.object(service.profile_store, "get_active_by_topic", return_value=active_profile):
            with patch.object(service, "_list_all_profile_evidence", return_value=[]):
                with patch.object(service, "_build_profile_support_index", return_value={}):
                    with patch.object(service, "_profile_support_snapshot", return_value={"avg_confidence": 0.3, "max_confidence": 0.3, "distinct_group_count": 0, "evidence_count": 0, "primary_strength": "", "direct_confirm_count": 0, "confirmed_count": 0}):
                        with patch.object(service, "_support_score", return_value=0.59):
                            with patch.object(service.candidate_profile_store, "upsert_demoted_profile") as mocked_candidate: 
                                with patch.object(service.profile_store, "supersede_profile", return_value=True) as mocked_supersede:
                                    with patch.object(service, "_rebuild_touched_topics") as mocked_rebuild:
                                        result = service.reconcile_topics([{"topic_id": "topic-1", "topic": "설명 선호"}])

        self.assertEqual(result["demoted_profiles"], 1)
        mocked_candidate.assert_called_once()
        mocked_supersede.assert_called_once_with("profile-1")
        mocked_rebuild.assert_called_once()

    def test_reconcile_topics_keeps_confirmed_profile_at_or_above_threshold(self) -> None:
        service = MemoryApplyService()
        active_profile = {
            "id": "profile-1",
            "topic_id": "topic-1",
            "topic": "설명 선호",
            "content": "구조적 설명을 선호한다",
            "confidence": 0.82,
            "source": "evidence_promotion:explicit_self_statement",
        }

        with patch.object(service.profile_store, "get_active_by_topic", return_value=active_profile):
            with patch.object(service, "_list_all_profile_evidence", return_value=[]):
                with patch.object(service, "_build_profile_support_index", return_value={}):
                    with patch.object(service, "_profile_support_snapshot", return_value={"avg_confidence": 0.7, "max_confidence": 0.7, "distinct_group_count": 1, "evidence_count": 1, "primary_strength": "explicit_self_statement", "direct_confirm_count": 0, "confirmed_count": 0}):
                        with patch.object(service, "_support_score", return_value=0.60):
                            with patch.object(service.candidate_profile_store, "upsert_demoted_profile") as mocked_candidate: 
                                with patch.object(service.profile_store, "supersede_profile", return_value=True) as mocked_supersede:
                                    result = service.reconcile_topics([{"topic_id": "topic-1", "topic": "설명 선호"}])

        self.assertEqual(result["demoted_profiles"], 0)
        mocked_candidate.assert_not_called()
        mocked_supersede.assert_not_called()


class MemoryApplyServiceCandidateRefreshTests(unittest.TestCase):
    def test_refresh_matching_candidate_profile_updates_semantic_match(self) -> None:
        service = MemoryApplyService()
        cluster = {
            "topic": "설명 선호",
            "topic_id": "topic-1",
            "candidate_content": "구조를 먼저 설명하는 방식을 선호한다",
            "primary_strength": "repeated_behavior",
            "avg_confidence": 0.62,
            "max_confidence": 0.71,
            "distinct_group_count": 2,
            "evidence_count": 2,
            "direct_confirm_count": 0,
            "confirmed_count": 0,
        }
        active_candidates = [
            {
                "id": "candidate-1",
                "content": "구조적 설명을 더 선호한다",
                "confidence": 0.58,
            }
        ]

        with patch.object(service.candidate_profile_store, "list_active_by_topic", return_value=active_candidates) as mocked_list:
            with patch.object(service, "_same_meaning", return_value=True):
                with patch.object(service, "_support_score", return_value=0.67):
                    with patch.object(service.candidate_profile_store, "update_active_candidate", return_value=True) as mocked_update:
                        refreshed = service._refresh_matching_candidate_profile(cluster=cluster)

        self.assertTrue(refreshed)
        mocked_list.assert_called_once_with(topic="설명 선호", topic_id="topic-1", limit=8)
        mocked_update.assert_called_once()
        self.assertEqual(mocked_update.call_args.args[0], "candidate-1")
        self.assertEqual(mocked_update.call_args.kwargs["support_score"], 0.67)
        self.assertEqual(mocked_update.call_args.kwargs["source"], "candidate_refresh:repeated_behavior")

    def test_archive_matching_candidate_profiles_uses_semantic_match(self) -> None:
        service = MemoryApplyService()
        active_candidates = [
            {"id": "candidate-1", "content": "구조적 설명을 선호한다"},
            {"id": "candidate-2", "content": "예시보다 구조를 더 선호한다"},
        ]

        def fake_same_meaning(left: str, right: str) -> bool:
            return "구조" in left and "구조" in right

        with patch.object(service.candidate_profile_store, "list_active_by_topic", return_value=active_candidates):
            with patch.object(service, "_same_meaning", side_effect=fake_same_meaning):
                with patch.object(service.candidate_profile_store, "archive_ids", return_value=2) as mocked_archive:
                    archived = service._archive_matching_candidate_profiles(
                        topic="설명 선호",
                        topic_id="topic-1",
                        content="구조를 먼저 설명해주는 방식을 선호한다",
                    )

        self.assertEqual(archived, 2)
        mocked_archive.assert_called_once_with(["candidate-1", "candidate-2"], status="promoted")


class ProfileEvidenceGraphClusterTests(unittest.TestCase):
    def test_build_candidate_clusters_groups_semantic_matches_and_keeps_shape(self) -> None:
        graph = ProfileEvidenceGraph()
        policy = MemoryClassificationPolicy()
        evidences = [
            {
                "id": "e1",
                "topic": "?ㅻ챸 ?좏샇",
                "topic_id": "topic-1",
                "candidate_content": "援ъ“瑜?癒쇱? ?ㅻ챸?섎뒗 諛⑹떇???좏샇?쒕떎",
                "source_strength": "repeated_behavior",
                "confidence": 0.58,
                "group_id": "group-1",
                "source_file_path": "notes/a.md",
                "memory_tier": "candidate",
                "channel": "uploaded_text",
                "linked_profile_id": "",
                "direct_confirm": False,
            },
            {
                "id": "e2",
                "topic": "?ㅻ챸 ?좏샇",
                "topic_id": "topic-1",
                "candidate_content": "援ъ“???ㅻ챸???癒쇱? ?섎뒗 寃껋쓣 ?좏샇?쒕떎",
                "source_strength": "explicit_self_statement",
                "confidence": 0.82,
                "group_id": "group-2",
                "source_file_path": "notes/b.md",
                "memory_tier": "confirmed",
                "channel": "chat",
                "linked_profile_id": "profile-1",
                "direct_confirm": True,
            },
            {
                "id": "e3",
                "topic": "?깆뾽 諛⑹떇",
                "topic_id": "topic-2",
                "candidate_content": "?쬆???쒗뻾?곸쑝濡?諛섏쑝??諛⑹떇???좏샇?쒕떎",
                "source_strength": "temporary_interest",
                "confidence": 0.43,
                "group_id": "group-3",
                "source_file_path": "notes/c.md",
                "memory_tier": "candidate",
                "channel": "project_artifact",
                "linked_profile_id": "",
                "direct_confirm": False,
            },
        ]

        def fake_similarity(left: str | None, right: str | None) -> float:
            joined = f"{left or ''} {right or ''}"
            if "?ㅻ챸" in joined and "援ъ“" in joined:
                return 0.91
            return 0.19

        with patch.object(graph, "semantic_similarity", side_effect=fake_similarity):
            clusters = graph.build_candidate_clusters(
                evidences,
                memory_policy=policy,
                source_strength_order=SOURCE_STRENGTH_ORDER,
            )

        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0]["topic_id"], "topic-1")
        self.assertEqual(clusters[0]["candidate_content"], "援ъ“???ㅻ챸???癒쇱? ?섎뒗 寃껋쓣 ?좏샇?쒕떎")
        self.assertEqual(clusters[0]["evidence_count"], 2)
        self.assertEqual(clusters[0]["distinct_group_count"], 2)
        self.assertEqual(clusters[0]["distinct_source_count"], 2)
        self.assertAlmostEqual(clusters[0]["avg_confidence"], 0.70)
        self.assertEqual(clusters[0]["max_confidence"], 0.82)
        self.assertEqual(clusters[0]["primary_strength"], "explicit_self_statement")
        self.assertEqual(clusters[0]["direct_confirm_count"], 1)
        self.assertEqual(clusters[0]["candidate_count"], 1)
        self.assertEqual(clusters[0]["confirmed_count"], 1)
        self.assertEqual(clusters[0]["channel_count"], 2)
        self.assertEqual(clusters[0]["linked_profile_ids"], {"profile-1"})
        self.assertEqual(clusters[1]["topic_id"], "topic-2")


class MemoryApplyServiceClusterDelegationTests(unittest.TestCase):
    def test_build_candidate_clusters_delegates_to_profile_graph(self) -> None:
        service = MemoryApplyService()
        evidences = [{"id": "e1", "candidate_content": "foo"}]
        sentinel = [{"topic": "general", "candidate_content": "foo"}]

        with patch.object(service.profile_graph, "build_candidate_clusters", return_value=sentinel) as mocked_build:
            result = service._build_candidate_clusters(evidences)

        self.assertIs(result, sentinel)
        mocked_build.assert_called_once_with(
            evidences,
            memory_policy=service.memory_policy,
            source_strength_order=SOURCE_STRENGTH_ORDER,
            semantic_cluster_threshold=PROFILE_SEMANTIC_CLUSTER_THRESHOLD,
        )


class ProfileEvidenceGraphSupportTests(unittest.TestCase):
    def test_build_profile_support_index_and_snapshot_and_score_keep_existing_shape(self) -> None:
        graph = ProfileEvidenceGraph()
        policy = MemoryClassificationPolicy()
        evidences = [
            {
                "linked_profile_id": "profile-1",
                "group_id": "group-1",
                "confidence": 0.62,
                "source_strength": "repeated_behavior",
                "memory_tier": "candidate",
                "direct_confirm": False,
            },
            {
                "linked_profile_id": "profile-1",
                "group_id": "group-2",
                "confidence": 0.85,
                "source_strength": "explicit_self_statement",
                "memory_tier": "confirmed",
                "direct_confirm": True,
            },
        ]

        support_index = graph.build_profile_support_index(evidences, memory_policy=policy)
        snapshot = graph.profile_support_snapshot(
            {"id": "profile-1", "confidence": 0.4, "source": "profile"},
            support_index,
            memory_policy=policy,
        )
        fallback_snapshot = graph.profile_support_snapshot(
            {
                "id": "profile-2",
                "confidence": 0.7,
                "source": "evidence_promotion:explicit_self_statement",
            },
            support_index,
            memory_policy=policy,
        )
        score = graph.support_score(snapshot, source_strength_order=SOURCE_STRENGTH_ORDER)

        self.assertEqual(snapshot["distinct_group_count"], 2)
        self.assertAlmostEqual(snapshot["avg_confidence"], 0.735)
        self.assertEqual(snapshot["max_confidence"], 0.85)
        self.assertEqual(snapshot["primary_strength"], "explicit_self_statement")
        self.assertEqual(snapshot["direct_confirm_count"], 1)
        self.assertEqual(snapshot["confirmed_count"], 1)
        self.assertEqual(snapshot["evidence_count"], 2)
        self.assertEqual(fallback_snapshot["primary_strength"], "explicit_self_statement")
        self.assertEqual(fallback_snapshot["direct_confirm_count"], 0)
        self.assertAlmostEqual(score, 1.73)


class MemoryApplyServiceSupportDelegationTests(unittest.TestCase):
    def test_support_methods_delegate_to_profile_graph(self) -> None:
        service = MemoryApplyService()
        evidences = [{"linked_profile_id": "profile-1"}]
        active_profile = {"id": "profile-1", "confidence": 0.8, "source": "profile"}
        support_index = {"profile-1": {"avg_confidence": 0.8}}
        snapshot = {"avg_confidence": 0.8}

        with patch.object(service.profile_graph, "build_profile_support_index", return_value={"profile-1": {}}) as mocked_index:
            result_index = service._build_profile_support_index(evidences)
        with patch.object(service.profile_graph, "profile_support_snapshot", return_value={"avg_confidence": 0.5}) as mocked_snapshot:
            result_snapshot = service._profile_support_snapshot(active_profile, support_index)
        with patch.object(service.profile_graph, "support_score", return_value=0.77) as mocked_score:
            result_score = service._support_score(snapshot)
        with patch.object(service.profile_graph, "source_strength_from_profile_source", return_value="explicit_self_statement") as mocked_strength:
            result_strength = service._source_strength_from_profile_source("evidence_promotion:explicit_self_statement")

        self.assertEqual(result_index, {"profile-1": {}})
        mocked_index.assert_called_once_with(evidences, memory_policy=service.memory_policy)

        self.assertEqual(result_snapshot, {"avg_confidence": 0.5})
        mocked_snapshot.assert_called_once_with(
            active_profile,
            support_index,
            memory_policy=service.memory_policy,
        )

        self.assertEqual(result_score, 0.77)
        mocked_score.assert_called_once_with(
            snapshot,
            source_strength_order=SOURCE_STRENGTH_ORDER,
        )

        self.assertEqual(result_strength, "explicit_self_statement")
        mocked_strength.assert_called_once_with(
            "evidence_promotion:explicit_self_statement",
            memory_policy=service.memory_policy,
        )


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
            with patch.object(service.evidence_store, "list_by_project_paths", return_value=[]):
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


class MemoryIngressProjectHashPassThroughTests(unittest.TestCase):
    def test_persist_project_profile_candidates_forwards_hash_map(self) -> None:
        service = MemoryIngressService()
        candidates = [
            {
                "candidate_content": "사용자는 구조적 설명을 좋아한다",
                "topic": "설명 선호",
                "evidence_text": "구조적으로 설명해달라고 말했다",
                "source_strength": "explicit_self_statement",
                "confidence": 0.9,
                "source_file_paths": ["docs/a.md"],
            }
        ]

        with patch.object(service.project_evidence_store, "add", return_value={}) as mocked_add:
            service.persist_project_profile_candidates(
                project_id="project-1",
                candidates=candidates,
                source_file_hash_by_path={"docs/a.md": "hash-a"},
            )

        self.assertEqual(mocked_add.call_count, 1)
        self.assertEqual(mocked_add.call_args.kwargs["source_file_hashes"], {"docs/a.md": "hash-a"})


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


    def test_profile_question_reconciles_affected_topics(self) -> None:
        service = ProjectAskService()

        with patch.object(service.profile_route_resolver, "resolve", return_value="profile_question"):
            with patch.object(
                service.profile_evidence_service,
                "ensure_extracted",
                return_value={
                    "stored": True,
                    "reused": False,
                    "needs_memory_sync": False,
                    "needs_support_reconcile": True,
                    "affected_topics": [{"topic_id": "topic-1", "topic": "설명 선호"}],
                },
            ):
                with patch.object(
                    service.profile_evidence_service,
                    "answer_from_project",
                    return_value={"answer": "프로필 답변", "used_profile_evidence": []},
                ):
                    with patch.object(service.memory_ingress_service, "sync_project") as mocked_sync:
                        with patch.object(service.memory_ingress_service, "reconcile_topics", return_value={"demoted_profiles": 1}) as mocked_reconcile:
                            with patch.object(service.project_review_store, "add"):
                                result = service.ask("project-1", "이 프로젝트로 본 내 성향은?", model="gemma3:4b")

        mocked_sync.assert_not_called()
        mocked_reconcile.assert_called_once_with([{"topic_id": "topic-1", "topic": "설명 선호"}])
        self.assertEqual(result["profile_memory_reconcile"], {"demoted_profiles": 1})


if __name__ == "__main__":
    unittest.main()
