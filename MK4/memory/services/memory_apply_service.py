from __future__ import annotations

import time

from config import (
    PROFILE_REPLACEMENT_SCORE_TOLERANCE,
    PROFILE_SEMANTIC_CLUSTER_THRESHOLD,
    PROFILE_SEMANTIC_MATCH_THRESHOLD,
    PROFILE_DEMOTE_MIN_SUPPORT_SCORE,
)
from memory.policies.memory_classification_policy import MemoryClassificationPolicy, SOURCE_STRENGTH_ORDER
from memory.services.profile_evidence_graph import ProfileEvidenceGraph
from memory.stores.chat_profile_evidence_store import ChatProfileEvidenceStore
from memory.stores.candidate_profile_store import CandidateProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.profile_store import ProfileStore
from memory.stores.state_store import StateStore
from memory.stores.topic_store import TopicStore
from memory.summarization.profile_rebuilder import ProfileRebuilder
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore


def _log(message: str) -> None:
    print(f"[MEMORY] {message}", flush=True)


class MemoryApplyService:
    """Single write/apply engine for every memory-producing channel."""

    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.episode_store = EpisodeStore()
        self.state_store = StateStore()
        self.profile_rebuilder = ProfileRebuilder()
        self.topic_store = TopicStore()
        self.memory_policy = MemoryClassificationPolicy()
        self.project_evidence_store = ProjectProfileEvidenceStore()
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.chat_evidence_store = ChatProfileEvidenceStore()
        self.candidate_profile_store = CandidateProfileStore()
        self.profile_graph = ProfileEvidenceGraph(topic_store=self.topic_store)

    def _normalize_text(self, text: str) -> str:
        return self.profile_graph.normalize_text(text)

    def _content_embedding(self, text: str) -> list[float]:
        return self.profile_graph.content_embedding(text)

    def _semantic_similarity(self, a: str, b: str) -> float:
        return self.profile_graph.semantic_similarity(a, b)

    def _same_meaning(
        self,
        a: str,
        b: str,
        *,
        threshold: float = PROFILE_SEMANTIC_MATCH_THRESHOLD,
    ) -> bool:
        return self.profile_graph.same_meaning(a, b, threshold=threshold)

    def _topic_label(self, topic: str | None, topic_id: str | None) -> str:
        return self.profile_graph.topic_label(topic=topic, topic_id=topic_id)

    def _correction_target_kind_from_reason(self, reason: str | None) -> str:
        text = str(reason or "").strip()
        prefix, has_separator, _rest = text.partition(":")
        if has_separator and prefix in {"profile", "topic_fact", "response_behavior"}:
            return prefix
        return "topic_fact"

    def _encode_correction_reason(self, *, reason: str | None, target_kind: str | None) -> str:
        reason_text = str(reason or "").strip() or "explicit_correction"
        normalized_kind = str(target_kind or "").strip().lower()
        if normalized_kind not in {"profile", "topic_fact", "response_behavior"}:
            normalized_kind = "topic_fact"
        return f"{normalized_kind}:{reason_text}"

    def _has_conflicting_active_correction(self, candidate_content: str, topic: str | None = None, topic_id: str | None = None) -> bool:
        if topic_id or (topic and str(topic).strip().lower() != "general"):
            active_corrections = self.correction_store.list_active_by_topic(
                topic=topic,
                topic_id=topic_id,
                limit=20,
            )
        else:
            active_corrections = self.correction_store.list_active(limit=20)
        for correction in active_corrections:
            if self._correction_target_kind_from_reason(correction.get("reason")) != "profile":
                continue
            correction_content = str(correction.get("content") or "").strip()
            if correction_content and self._same_meaning(correction_content, candidate_content):
                return True

            supersedes_profile_id = str(correction.get("supersedes_profile_id") or "").strip()
            if not supersedes_profile_id:
                continue

            superseded_profile = self.profile_store.get_profile_by_id(supersedes_profile_id)
            if not superseded_profile:
                continue

            superseded_content = str(superseded_profile.get("content") or "").strip()
            if superseded_content and self._same_meaning(superseded_content, candidate_content):
                return True
        return False

    def _store_chat_profile_evidence(self, evidence: dict) -> dict:
        return self.chat_evidence_store.add(
            evidence_type="profile_candidate",
            source_message_id=evidence.get("source_message_id"),
            response_message_id=evidence.get("response_message_id"),
            topic=evidence.get("topic"),
            topic_id=evidence.get("topic_id"),
            candidate_content=evidence.get("candidate_content"),
            source_strength=evidence.get("source_strength"),
            evidence_text=evidence.get("evidence_text"),
            confidence=evidence.get("confidence"),
            memory_tier=evidence.get("memory_tier"),
            direct_confirm=bool(evidence.get("direct_confirm")),
        )

    def _matching_candidate_profiles(self, *, topic: str, topic_id: str | None, content: str, limit: int = 8) -> list[dict]:
        matches: list[dict] = []
        for candidate in self.candidate_profile_store.list_active_by_topic(topic=topic, topic_id=topic_id, limit=limit):
            candidate_content = str(candidate.get("content") or "").strip()
            if candidate_content and self._same_meaning(candidate_content, content):
                matches.append(candidate)
        return matches

    def _archive_matching_candidate_profiles(self, *, topic: str, topic_id: str | None, content: str) -> int:
        matches = self._matching_candidate_profiles(topic=topic, topic_id=topic_id, content=content)
        candidate_ids = [str(item.get("id") or "").strip() for item in matches if str(item.get("id") or "").strip()]
        if not candidate_ids:
            return 0
        return self.candidate_profile_store.archive_ids(candidate_ids, status="promoted")

    def _refresh_matching_candidate_profile(self, *, cluster: dict) -> bool:
        topic = cluster["topic"]
        topic_id = cluster.get("topic_id")
        candidate_content = str(cluster.get("candidate_content") or "").strip()
        if not candidate_content:
            return False

        matches = self._matching_candidate_profiles(topic=topic, topic_id=topic_id, content=candidate_content)
        if not matches:
            return False

        primary = matches[0]
        refreshed = self.candidate_profile_store.update_active_candidate(
            str(primary.get("id") or "").strip(),
            confidence=max(
                float(primary.get("confidence") or 0.0),
                self.memory_policy.promotion_confidence(cluster),
            ),
            support_score=self._support_score(cluster),
            source=f"candidate_refresh:{cluster['primary_strength'] or 'mixed'}",
        )
        duplicate_ids = [str(item.get("id") or "").strip() for item in matches[1:] if str(item.get("id") or "").strip()]
        if duplicate_ids:
            self.candidate_profile_store.archive_ids(duplicate_ids, status="merged")
        return refreshed

    def _insert_or_link_confirmed_profile(self, *, topic: str, topic_id: str | None, content: str, source: str, confidence: float) -> tuple[str, bool]:
        active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
        if active_profile and self._same_meaning(str(active_profile.get("content") or ""), content):
            self._archive_matching_candidate_profiles(topic=topic, topic_id=topic_id, content=content)
            return str(active_profile["id"]), False
        new_profile_id = self.profile_store.insert_profile(
            topic=topic,
            topic_id=topic_id,
            content=content,
            source=source,
            confidence=confidence,
        )
        self._archive_matching_candidate_profiles(topic=topic, topic_id=topic_id, content=content)
        return str(new_profile_id), True

    def _build_candidate_clusters(self, evidences: list[dict]) -> list[dict]:
        return self.profile_graph.build_candidate_clusters(
            evidences,
            memory_policy=self.memory_policy,
            source_strength_order=SOURCE_STRENGTH_ORDER,
            semantic_cluster_threshold=PROFILE_SEMANTIC_CLUSTER_THRESHOLD,
        )

    def _list_all_profile_evidence(self) -> list[dict]:
        result: list[dict] = []
        for item in self.project_evidence_store.list_profile_evidence():
            copied = dict(item)
            copied["group_id"] = copied.get("project_id")
            copied["channel"] = "project_artifact"
            copied["store_kind"] = "project_artifact"
            result.append(copied)
        for item in self.uploaded_evidence_store.list_profile_evidence():
            copied = dict(item)
            copied["group_id"] = copied.get("source_id")
            copied["channel"] = "uploaded_text"
            copied["store_kind"] = "uploaded_text"
            result.append(copied)
        for item in self.chat_evidence_store.list_profile_evidence():
            copied = dict(item)
            copied["group_id"] = copied.get("source_message_id") or copied.get("response_message_id")
            copied["channel"] = "chat"
            copied["store_kind"] = "chat"
            result.append(copied)
        return result

    def _link_profile_for_evidence_rows(self, *, evidence_rows: list[dict], profile_id: str) -> int:
        linked = 0
        for evidence in evidence_rows:
            evidence_id = str(evidence.get("id") or "").strip()
            store_kind = str(evidence.get("store_kind") or "").strip()
            if not evidence_id or not store_kind:
                continue
            if store_kind == "project_artifact":
                self.project_evidence_store.mark_applied(evidence_id, linked_profile_id=profile_id)
            elif store_kind == "uploaded_text":
                self.uploaded_evidence_store.mark_applied(evidence_id, linked_profile_id=profile_id)
            elif store_kind == "chat":
                self.chat_evidence_store.mark_applied(evidence_id, linked_profile_id=profile_id)
            else:
                continue
            linked += 1
        return linked

    def _source_strength_from_profile_source(self, source: str | None) -> str:
        return self.profile_graph.source_strength_from_profile_source(
            source,
            memory_policy=self.memory_policy,
        )

    def _build_profile_support_index(self, evidences: list[dict]) -> dict[str, dict]:
        return self.profile_graph.build_profile_support_index(
            evidences,
            memory_policy=self.memory_policy,
        )

    def _profile_support_snapshot(self, active_profile: dict, support_index: dict[str, dict]) -> dict:
        return self.profile_graph.profile_support_snapshot(
            active_profile,
            support_index,
            memory_policy=self.memory_policy,
        )

    def _support_score(self, snapshot: dict) -> float:
        return self.profile_graph.support_score(
            snapshot,
            source_strength_order=SOURCE_STRENGTH_ORDER,
        )

    def _should_replace_active_profile(self, active_profile: dict, cluster: dict, support_index: dict[str, dict]) -> tuple[bool, str]:
        active_support = self._profile_support_snapshot(active_profile, support_index)
        candidate_score = self._support_score(cluster)
        active_score = self._support_score(active_support)

        active_direct_confirm = int(active_support.get("direct_confirm_count") or 0)
        candidate_direct_confirm = int(cluster.get("direct_confirm_count") or 0)
        if candidate_direct_confirm > active_direct_confirm:
            if float(cluster.get("max_confidence") or 0.0) >= float(active_support.get("max_confidence") or 0.0) - 0.10:
                return True, "replace_with_direct_confirm"

        if float(cluster.get("max_confidence") or 0.0) >= float(active_support.get("max_confidence") or 0.0) + 0.03:
            return True, "replace_with_higher_confidence"

        if candidate_score + PROFILE_REPLACEMENT_SCORE_TOLERANCE >= active_score:
            return True, "replace_with_fresh_stronger_or_equal_cluster"

        return False, "existing_profile_still_stronger"

    def _demote_profile_to_candidate(self, *, active_profile: dict, support_snapshot: dict, support_score: float) -> bool:
        profile_id = str(active_profile.get("id") or "").strip()
        if not profile_id:
            return False

        topic_id = str(active_profile.get("topic_id") or "").strip() or None
        topic = self._topic_label(
            active_profile.get("topic_name") or active_profile.get("topic_summary") or active_profile.get("topic"),
            topic_id,
        )
        self.candidate_profile_store.upsert_demoted_profile(
            topic=topic,
            topic_id=topic_id,
            content=str(active_profile.get("content") or "").strip(),
            source=f"demoted_confirmed:{active_profile.get('source') or 'profile'}",
            confidence=float(active_profile.get("confidence") or 0.0),
            support_score=float(support_score or 0.0),
            source_profile_id=profile_id,
        )
        return self.profile_store.supersede_profile(profile_id)

    def _demote_weak_active_profiles(
        self,
        *,
        topic_keys: set[tuple[str | None, str]],
        support_index: dict[str, dict],
    ) -> tuple[int, set[tuple[str | None, str]]]:
        demoted_profiles = 0
        touched_topics: set[tuple[str | None, str]] = set()

        for topic_id, topic in topic_keys:
            active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
            if not active_profile:
                continue
            support_snapshot = self._profile_support_snapshot(active_profile, support_index)
            support_score = self._support_score(support_snapshot)
            if support_score >= PROFILE_DEMOTE_MIN_SUPPORT_SCORE:
                continue
            if self._demote_profile_to_candidate(
                active_profile=active_profile,
                support_snapshot=support_snapshot,
                support_score=support_score,
            ):
                demoted_profiles += 1
                touched_topics.add((topic_id, topic))
        return demoted_profiles, touched_topics

    def reconcile_topics(self, topic_refs: list[dict] | None) -> dict:
        normalized_topic_keys: set[tuple[str | None, str]] = set()
        for item in topic_refs or []:
            topic_id = str(item.get("topic_id") or "").strip() or None
            topic = self._topic_label(item.get("topic"), topic_id)
            normalized_topic_keys.add((topic_id, topic))

        if not normalized_topic_keys:
            return {"reconciled_topics": 0, "demoted_profiles": 0}

        evidences = self._list_all_profile_evidence()
        support_index = self._build_profile_support_index(evidences)
        demoted_profiles, touched_topics = self._demote_weak_active_profiles(
            topic_keys=normalized_topic_keys,
            support_index=support_index,
        )
        self._rebuild_touched_topics(touched_topics)
        return {
            "reconciled_topics": len(normalized_topic_keys),
            "demoted_profiles": demoted_profiles,
        }

    def _rebuild_touched_topics(self, touched_topics: set[tuple[str | None, str]]) -> None:
        for topic_id, topic in touched_topics:
            self.profile_rebuilder.rebuild_topic(topic=topic, topic_id=topic_id)

    def _empty_promotion_result(self) -> dict:
        return {
            "promoted_profiles": 0,
            "replaced_active_profiles": 0,
            "linked_existing_profiles": 0,
            "blocked_by_correction": 0,
            "blocked_by_existing_profile_conflict": 0,
            "pending_candidates": 0,
            "refreshed_candidates": 0,
            "demoted_profiles": 0,
            "promoted_topics": set(),
        }

    def apply_extracted(self, extracted: dict) -> dict:
        started_at = time.perf_counter()
        touched_topics: set[tuple[str | None, str]] = set()
        applied = {
            "states": 0,
            "profiles": 0,
            "episodes": 0,
            "corrections": 0,
            "stored_profile_evidence": 0,
            "rebuilt_topics": 0,
        }

        t0 = time.perf_counter()
        for state in extracted.get("states", []):
            key = state["key"]
            value = state.get("value", "")
            if key == "active_topic_id" and not value:
                continue
            self.state_store.set_state(key, value, state.get("source", "user_explicit"))
            applied["states"] += 1
        states_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        for profile in extracted.get("profiles", []):
            topic = profile.get("topic") or profile.get("topic_summary") or "general"
            topic_id = profile.get("topic_id")
            self.profile_store.insert_profile(
                topic=topic,
                content=profile["content"],
                source=profile.get("source", "user_explicit"),
                confidence=profile.get("confidence", 1.0),
                topic_id=topic_id,
            )
            touched_topics.add((topic_id, topic))
            applied["profiles"] += 1
        profiles_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        for evidence in extracted.get("profile_evidences", []):
            stored = self._store_chat_profile_evidence(evidence)
            applied["stored_profile_evidence"] += 1
            if evidence.get("memory_tier") == "confirmed":
                topic = evidence.get("topic") or "general"
                topic_id = evidence.get("topic_id")
                profile_id, inserted = self._insert_or_link_confirmed_profile(
                    topic=topic,
                    topic_id=topic_id,
                    content=evidence.get("candidate_content") or "",
                    source="chat_direct_confirm",
                    confidence=float(evidence.get("confidence") or 0.0),
                )
                self.chat_evidence_store.mark_applied(stored["id"], linked_profile_id=profile_id)
                if inserted:
                    touched_topics.add((topic_id, topic))
                    applied["profiles"] += 1
        evidence_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        for episode in extracted.get("episodes", []):
            topic = episode.get("topic") or episode.get("topic_summary") or "general"
            topic_id = episode.get("topic_id")
            self.episode_store.create_episode(
                topic=topic,
                topic_id=topic_id,
                summary=episode["summary"],
                raw_ref=episode.get("raw_ref"),
                importance=episode.get("importance", 0.5),
            )
            touched_topics.add((topic_id, topic))
            applied["episodes"] += 1
        episodes_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        for correction in extracted.get("corrections", []):
            topic = correction.get("topic") or correction.get("topic_summary") or "general"
            topic_id = correction.get("topic_id")
            target_kind = str(correction.get("target_kind") or "").strip().lower() or "topic_fact"
            active_profile = None
            supersedes_profile_id = None
            if target_kind == "profile":
                active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
                if active_profile and str(active_profile.get("content") or "").strip() != str(correction["content"] or "").strip():
                    supersedes_profile_id = active_profile["id"]
            self.correction_store.add_correction(
                topic=topic,
                topic_id=topic_id,
                content=correction["content"],
                reason=self._encode_correction_reason(
                    reason=correction.get("reason", "explicit_correction"),
                    target_kind=target_kind,
                ),
                source=correction.get("source", "user_explicit"),
                supersedes_profile_id=supersedes_profile_id,
            )
            touched_topics.add((topic_id, topic))
            applied["corrections"] += 1
        corrections_elapsed = time.perf_counter() - t0

        should_run_promotion = bool(extracted.get("profile_evidences"))
        if should_run_promotion:
            t0 = time.perf_counter()
            promotion_result = self._promote_profiles_from_evidence_pool()
            promotion_elapsed = time.perf_counter() - t0
        else:
            promotion_result = self._empty_promotion_result()
            promotion_elapsed = 0.0
        for topic_key in promotion_result.pop("promoted_topics", set()):
            touched_topics.add(topic_key)

        t0 = time.perf_counter()
        self._rebuild_touched_topics(touched_topics)
        rebuild_elapsed = time.perf_counter() - t0
        applied["rebuilt_topics"] = len(touched_topics)
        applied.update(promotion_result)

        total_elapsed = time.perf_counter() - started_at
        _log(
            "memory_apply apply_extracted | "            f"states={states_elapsed:.2f}s | profiles={profiles_elapsed:.2f}s | "            f"evidence={evidence_elapsed:.2f}s | episodes={episodes_elapsed:.2f}s | "            f"corrections={corrections_elapsed:.2f}s | promotion={promotion_elapsed:.2f}s | "            f"rebuild={rebuild_elapsed:.2f}s | total={total_elapsed:.2f}s"        )
        return applied

    def _promote_profiles_from_evidence_pool(self) -> dict:
        started_at = time.perf_counter()

        t0 = time.perf_counter()
        evidences = self._list_all_profile_evidence()
        list_elapsed = time.perf_counter() - t0

        t0 = time.perf_counter()
        clusters = self._build_candidate_clusters(evidences)
        support_index = self._build_profile_support_index(evidences)
        cluster_elapsed = time.perf_counter() - t0

        promoted_profiles = 0
        replaced_active_profiles = 0
        linked_existing_profiles = 0
        blocked_by_correction = 0
        blocked_by_existing_profile_conflict = 0
        pending_candidates = 0
        refreshed_candidates = 0
        promoted_topics: set[tuple[str | None, str]] = set()

        t0 = time.perf_counter()
        for cluster in clusters:
            topic_id = cluster.get("topic_id")
            topic = cluster["topic"]
            candidate_content = cluster["candidate_content"]

            promotable, _reason = self.memory_policy.is_promotable_cluster(cluster)
            if not promotable:
                if self._refresh_matching_candidate_profile(cluster=cluster):
                    refreshed_candidates += 1
                pending_candidates += 1
                continue
            if self._has_conflicting_active_correction(candidate_content, topic=topic, topic_id=topic_id):
                blocked_by_correction += 1
                continue

            active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
            if active_profile:
                active_content = str(active_profile.get("content") or "").strip()
                if self._same_meaning(active_content, candidate_content):
                    linked_count = self._link_profile_for_evidence_rows(
                        evidence_rows=cluster.get("evidence_rows") or [],
                        profile_id=active_profile["id"],
                    )
                    self._archive_matching_candidate_profiles(topic=topic, topic_id=topic_id, content=candidate_content)
                    if linked_count > 0:
                        linked_existing_profiles += 1
                    continue

                should_replace, _replace_reason = self._should_replace_active_profile(active_profile, cluster, support_index)
                if not should_replace:
                    blocked_by_existing_profile_conflict += 1
                    continue
                replaced_active_profiles += 1

            new_profile_id = self.profile_store.insert_profile(
                topic=topic,
                topic_id=topic_id,
                content=candidate_content,
                source=f"evidence_promotion:{cluster['primary_strength'] or 'mixed'}",
                confidence=self.memory_policy.promotion_confidence(cluster),
            )
            self._archive_matching_candidate_profiles(topic=topic, topic_id=topic_id, content=candidate_content)
            self._link_profile_for_evidence_rows(
                evidence_rows=cluster.get("evidence_rows") or [],
                profile_id=new_profile_id,
            )
            promoted_profiles += 1
            promoted_topics.add((topic_id, topic))
        demoted_profiles, demoted_topics = self._demote_weak_active_profiles(
            topic_keys=promoted_topics or {
                (cluster.get("topic_id"), cluster.get("topic"))
                for cluster in clusters
            },
            support_index=self._build_profile_support_index(self._list_all_profile_evidence()),
        )
        promoted_topics.update(demoted_topics)
        loop_elapsed = time.perf_counter() - t0

        total_elapsed = time.perf_counter() - started_at
        _log(
            "memory_apply promote_pool | "            f"list_evidence={list_elapsed:.2f}s | build_clusters={cluster_elapsed:.2f}s | "            f"loop={loop_elapsed:.2f}s | evidences={len(evidences)} | clusters={len(clusters)} | total={total_elapsed:.2f}s"        )
        return {
            "promoted_profiles": promoted_profiles,
            "replaced_active_profiles": replaced_active_profiles,
            "linked_existing_profiles": linked_existing_profiles,
            "blocked_by_correction": blocked_by_correction,
            "blocked_by_existing_profile_conflict": blocked_by_existing_profile_conflict,
            "pending_candidates": pending_candidates,
            "refreshed_candidates": refreshed_candidates,
            "demoted_profiles": demoted_profiles,
            "promoted_topics": promoted_topics,
        }

    def _sync_evidences(self, evidences: list[dict], evidence_store) -> dict:
        processed = 0
        linked_to_existing_active_profile = 0
        skipped = 0
        direct_confirm_inserted = 0
        direct_confirm_linked = 0
        touched_topics: set[tuple[str | None, str]] = set()

        for evidence in evidences:
            topic_id = str(evidence.get("topic_id") or "").strip() or None
            topic = self._topic_label(evidence.get("topic"), topic_id)
            candidate_content = (evidence.get("candidate_content") or "").strip()
            if not candidate_content:
                evidence_store.mark_applied(evidence["id"])
                skipped += 1
                processed += 1
                continue

            classification = self.memory_policy.classify_evidence(evidence)
            route = classification["route"]
            if route == "discard":
                evidence_store.mark_applied(evidence["id"])
                skipped += 1
                processed += 1
                continue

            if route == "confirmed":
                profile_id, inserted = self._insert_or_link_confirmed_profile(
                    topic=topic,
                    topic_id=topic_id,
                    content=candidate_content,
                    source=f"direct_confirm:{evidence.get('source_file_path') or 'evidence'}",
                    confidence=float(evidence.get("confidence") or 0.0),
                )
                evidence_store.mark_applied(evidence["id"], linked_profile_id=profile_id)
                if inserted:
                    direct_confirm_inserted += 1
                    touched_topics.add((topic_id, topic))
                else:
                    direct_confirm_linked += 1
                processed += 1
                continue

            active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
            if active_profile and self._same_meaning(active_profile.get("content", ""), candidate_content):
                evidence_store.mark_applied(evidence["id"], linked_profile_id=active_profile["id"])
                linked_to_existing_active_profile += 1
                processed += 1
                continue

            evidence_store.mark_applied(evidence["id"])
            processed += 1

        promotion_result = self._promote_profiles_from_evidence_pool()
        promoted_topics = promotion_result.pop("promoted_topics", set())
        touched_topics.update(promoted_topics)
        self._rebuild_touched_topics(touched_topics)

        return {
            "processed": processed,
            "inserted_profiles": promotion_result["promoted_profiles"] + direct_confirm_inserted,
            "added_corrections": 0,
            "linked_to_existing_active_profile": linked_to_existing_active_profile + direct_confirm_linked,
            "promoted_profiles": promotion_result["promoted_profiles"],
            "replaced_active_profiles": promotion_result["replaced_active_profiles"],
            "linked_existing_profiles": promotion_result["linked_existing_profiles"],
            "blocked_by_correction": promotion_result["blocked_by_correction"],
            "blocked_by_existing_profile_conflict": promotion_result["blocked_by_existing_profile_conflict"],
            "pending_candidates": promotion_result["pending_candidates"],
            "demoted_profiles": promotion_result.get("demoted_profiles", 0),
            "rebuilt_topics": len(touched_topics),
            "skipped": skipped,
            "direct_confirm_inserted": direct_confirm_inserted,
            "direct_confirm_linked": direct_confirm_linked,
        }

    def sync_project(self, project_id: str) -> dict:
        evidences = self.project_evidence_store.list_unapplied_by_project(project_id)
        return self._sync_evidences(evidences=evidences, evidence_store=self.project_evidence_store)

    def sync_uploaded_source(self, source_id: str) -> dict:
        evidences = self.uploaded_evidence_store.list_unapplied_by_source(source_id)
        return self._sync_evidences(evidences=evidences, evidence_store=self.uploaded_evidence_store)
