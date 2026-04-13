from __future__ import annotations

import time

from config import (
    PROFILE_REPLACEMENT_SCORE_TOLERANCE,
    PROFILE_SEMANTIC_CLUSTER_THRESHOLD,
    PROFILE_SEMANTIC_MATCH_THRESHOLD,
)
from memory.policies.memory_classification_policy import MemoryClassificationPolicy, SOURCE_STRENGTH_ORDER
from memory.stores.chat_profile_evidence_store import ChatProfileEvidenceStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.profile_store import ProfileStore
from memory.stores.state_store import StateStore
from memory.stores.topic_store import TopicStore
from memory.summarization.profile_rebuilder import ProfileRebuilder
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore
from tools.text_embedding import cosine_similarity, embed_text


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
        self._embedding_cache: dict[str, list[float]] = {}

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().split())

    def _content_embedding(self, text: str) -> list[float]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []
        if normalized not in self._embedding_cache:
            self._embedding_cache[normalized] = embed_text(normalized, kind="passage")
        return self._embedding_cache[normalized]

    def _semantic_similarity(self, a: str, b: str) -> float:
        left = self._content_embedding(a)
        right = self._content_embedding(b)
        return cosine_similarity(left, right)

    def _same_meaning(
        self,
        a: str,
        b: str,
        *,
        threshold: float = PROFILE_SEMANTIC_MATCH_THRESHOLD,
    ) -> bool:
        if not self._normalize_text(a) or not self._normalize_text(b):
            return False
        return self._semantic_similarity(a, b) >= threshold

    def _topic_label(self, topic: str | None, topic_id: str | None) -> str:
        if topic:
            return str(topic).strip() or "general"
        if topic_id:
            topic_row = self.topic_store.get_topic(topic_id)
            if topic_row:
                return str(topic_row.get("summary") or topic_row.get("name") or "general").strip() or "general"
        return "general"

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
        del topic, topic_id
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

    def _insert_or_link_confirmed_profile(self, *, topic: str, topic_id: str | None, content: str, source: str, confidence: float) -> tuple[str, bool]:
        active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
        if active_profile and self._same_meaning(str(active_profile.get("content") or ""), content):
            return str(active_profile["id"]), False
        new_profile_id = self.profile_store.insert_profile(
            topic=topic,
            topic_id=topic_id,
            content=content,
            source=source,
            confidence=confidence,
        )
        return str(new_profile_id), True

    def _build_candidate_clusters(self, evidences: list[dict]) -> list[dict]:
        clusters: list[dict] = []

        for evidence in evidences:
            topic_id = str(evidence.get("topic_id") or "").strip() or None
            topic = self._topic_label(evidence.get("topic"), topic_id)
            candidate_content = (evidence.get("candidate_content") or "").strip()
            source_strength = (evidence.get("source_strength") or "").strip()
            memory_tier = self.memory_policy.normalize_memory_tier(evidence.get("memory_tier")) or self.memory_policy.classify_evidence(evidence)["route"]

            if not candidate_content or memory_tier == "discard":
                continue

            topic_key = topic_id or self._normalize_text(topic)
            matched_cluster = None
            best_similarity = 0.0
            for cluster in clusters:
                if cluster["topic_key"] != topic_key:
                    continue
                similarity = self._semantic_similarity(candidate_content, cluster["representative_content"])
                if similarity >= PROFILE_SEMANTIC_CLUSTER_THRESHOLD and similarity > best_similarity:
                    matched_cluster = cluster
                    best_similarity = similarity

            if matched_cluster is None:
                matched_cluster = {
                    "topic_key": topic_key,
                    "topic": topic,
                    "topic_id": topic_id,
                    "candidate_content": candidate_content,
                    "representative_content": candidate_content,
                    "representative_confidence": float(evidence.get("confidence") or 0.0),
                    "evidence_ids": [],
                    "evidence_rows": [],
                    "group_ids": set(),
                    "source_paths": set(),
                    "confidence_values": [],
                    "source_strength_counts": {
                        "explicit_self_statement": 0,
                        "repeated_behavior": 0,
                        "temporary_interest": 0,
                    },
                    "tier_counts": {"general": 0, "candidate": 0, "confirmed": 0},
                    "linked_profile_ids": set(),
                    "direct_confirm_count": 0,
                    "channels": set(),
                    "similarity_values": [],
                }
                clusters.append(matched_cluster)

            cluster = matched_cluster
            if not cluster.get("topic_id") and topic_id:
                cluster["topic_id"] = topic_id
            cluster["topic"] = self._topic_label(cluster.get("topic"), cluster.get("topic_id"))
            cluster["evidence_ids"].append(str(evidence.get("id") or ""))
            cluster["evidence_rows"].append(evidence)
            cluster["group_ids"].add(str(evidence.get("group_id") or ""))
            cluster["source_paths"].add(str(evidence.get("source_file_path") or evidence.get("source_message_id") or ""))
            cluster["confidence_values"].append(float(evidence.get("confidence") or 0.0))
            cluster["source_strength_counts"][source_strength] = cluster["source_strength_counts"].get(source_strength, 0) + 1
            cluster["tier_counts"][memory_tier] = cluster["tier_counts"].get(memory_tier, 0) + 1
            if bool(evidence.get("direct_confirm")):
                cluster["direct_confirm_count"] += 1
            if evidence.get("channel"):
                cluster["channels"].add(str(evidence.get("channel")))
            linked_profile_id = str(evidence.get("linked_profile_id") or "").strip()
            if linked_profile_id:
                cluster["linked_profile_ids"].add(linked_profile_id)
            cluster["similarity_values"].append(best_similarity or 1.0)
            confidence = float(evidence.get("confidence") or 0.0)
            if confidence >= float(cluster.get("representative_confidence") or 0.0):
                cluster["representative_confidence"] = confidence
                cluster["representative_content"] = candidate_content

        result: list[dict] = []
        for cluster in clusters:
            confidence_values = cluster["confidence_values"] or [0.0]
            source_strength_counts = cluster["source_strength_counts"]
            primary_strength = ""
            if source_strength_counts.get("explicit_self_statement", 0) > 0:
                primary_strength = "explicit_self_statement"
            elif source_strength_counts.get("repeated_behavior", 0) > 0:
                primary_strength = "repeated_behavior"
            elif source_strength_counts.get("temporary_interest", 0) > 0:
                primary_strength = "temporary_interest"

            result.append(
                {
                    "topic": cluster["topic"],
                    "topic_id": cluster.get("topic_id"),
                    "candidate_content": cluster["representative_content"],
                    "evidence_ids": cluster["evidence_ids"],
                    "evidence_rows": cluster["evidence_rows"],
                    "evidence_count": len(cluster["evidence_ids"]),
                    "distinct_group_count": len([x for x in cluster["group_ids"] if x]),
                    "distinct_source_count": len([x for x in cluster["source_paths"] if x]),
                    "avg_confidence": sum(confidence_values) / len(confidence_values),
                    "max_confidence": max(confidence_values),
                    "primary_strength": primary_strength,
                    "linked_profile_ids": cluster["linked_profile_ids"],
                    "direct_confirm_count": cluster["direct_confirm_count"],
                    "general_count": cluster["tier_counts"].get("general", 0),
                    "candidate_count": cluster["tier_counts"].get("candidate", 0),
                    "confirmed_count": cluster["tier_counts"].get("confirmed", 0),
                    "channel_count": len(cluster["channels"]),
                }
            )

        result.sort(
            key=lambda item: (
                -item["confirmed_count"],
                -SOURCE_STRENGTH_ORDER.get(item["primary_strength"], 0),
                -item["distinct_group_count"],
                -item["evidence_count"],
                -item["avg_confidence"],
                item["topic"],
            )
        )
        return result

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
        text = str(source or "").strip()
        if text.startswith("evidence_promotion:"):
            candidate = text.split(":", 1)[1].strip()
            return self.memory_policy.normalize_source_strength(candidate)
        if text.startswith("direct_confirm:") or text == "chat_direct_confirm":
            return "explicit_self_statement"
        return ""

    def _build_profile_support_index(self, evidences: list[dict]) -> dict[str, dict]:
        grouped: dict[str, dict] = {}

        for evidence in evidences:
            profile_id = str(evidence.get("linked_profile_id") or "").strip()
            if not profile_id:
                continue

            row = grouped.setdefault(
                profile_id,
                {
                    "group_ids": set(),
                    "confidence_values": [],
                    "source_strength_counts": {
                        "explicit_self_statement": 0,
                        "repeated_behavior": 0,
                        "temporary_interest": 0,
                    },
                    "direct_confirm_count": 0,
                    "confirmed_count": 0,
                    "evidence_count": 0,
                },
            )
            row["group_ids"].add(str(evidence.get("group_id") or ""))
            row["confidence_values"].append(float(evidence.get("confidence") or 0.0))
            row["evidence_count"] += 1

            strength = self.memory_policy.normalize_source_strength(evidence.get("source_strength"))
            if strength:
                row["source_strength_counts"][strength] = row["source_strength_counts"].get(strength, 0) + 1

            tier = self.memory_policy.normalize_memory_tier(evidence.get("memory_tier"))
            if tier == "confirmed":
                row["confirmed_count"] += 1
            if bool(evidence.get("direct_confirm")):
                row["direct_confirm_count"] += 1

        result: dict[str, dict] = {}
        for profile_id, row in grouped.items():
            confidence_values = row["confidence_values"] or [0.0]
            source_strength_counts = row["source_strength_counts"]
            primary_strength = ""
            if source_strength_counts.get("explicit_self_statement", 0) > 0:
                primary_strength = "explicit_self_statement"
            elif source_strength_counts.get("repeated_behavior", 0) > 0:
                primary_strength = "repeated_behavior"
            elif source_strength_counts.get("temporary_interest", 0) > 0:
                primary_strength = "temporary_interest"

            result[profile_id] = {
                "distinct_group_count": len([x for x in row["group_ids"] if x]),
                "avg_confidence": sum(confidence_values) / len(confidence_values),
                "max_confidence": max(confidence_values),
                "primary_strength": primary_strength,
                "direct_confirm_count": row["direct_confirm_count"],
                "confirmed_count": row["confirmed_count"],
                "evidence_count": row["evidence_count"],
            }
        return result

    def _profile_support_snapshot(self, active_profile: dict, support_index: dict[str, dict]) -> dict:
        profile_id = str(active_profile.get("id") or "").strip()
        if profile_id and profile_id in support_index:
            return dict(support_index[profile_id])

        source = str(active_profile.get("source") or "").strip()
        direct_confirm = 1 if source.startswith("direct_confirm:") or source == "chat_direct_confirm" else 0
        confidence = float(active_profile.get("confidence") or 0.0)
        return {
            "distinct_group_count": 1,
            "avg_confidence": confidence,
            "max_confidence": confidence,
            "primary_strength": self._source_strength_from_profile_source(source),
            "direct_confirm_count": direct_confirm,
            "confirmed_count": direct_confirm,
            "evidence_count": 1,
        }

    def _support_score(self, snapshot: dict) -> float:
        score = max(float(snapshot.get("avg_confidence") or 0.0), float(snapshot.get("max_confidence") or 0.0))
        score += 0.08 * min(int(snapshot.get("distinct_group_count") or 0), 3)
        score += 0.03 * min(max(int(snapshot.get("evidence_count") or 0) - 1, 0), 3)
        score += 0.08 * SOURCE_STRENGTH_ORDER.get(str(snapshot.get("primary_strength") or ""), 0)
        if int(snapshot.get("confirmed_count") or 0) > 0:
            score += 0.20
        if int(snapshot.get("direct_confirm_count") or 0) > 0:
            score += 0.25
        return score

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
        promoted_topics: set[tuple[str | None, str]] = set()

        t0 = time.perf_counter()
        for cluster in clusters:
            topic_id = cluster.get("topic_id")
            topic = cluster["topic"]
            candidate_content = cluster["candidate_content"]

            promotable, _reason = self.memory_policy.is_promotable_cluster(cluster)
            if not promotable:
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
            self._link_profile_for_evidence_rows(
                evidence_rows=cluster.get("evidence_rows") or [],
                profile_id=new_profile_id,
            )
            promoted_profiles += 1
            promoted_topics.add((topic_id, topic))
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
