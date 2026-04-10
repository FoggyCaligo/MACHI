from memory.policies.memory_classification_policy import (
    MemoryClassificationPolicy,
    SOURCE_STRENGTH_ORDER,
)
from memory.stores.correction_store import CorrectionStore
from memory.stores.profile_store import ProfileStore
from memory.stores.topic_store import TopicStore
from profile_analysis.stores.uploaded_profile_evidence_store import UploadedProfileEvidenceStore
from project_analysis.stores.project_profile_evidence_store import ProjectProfileEvidenceStore



class ProfileMemorySyncService:
    def __init__(self) -> None:
        self.project_evidence_store = ProjectProfileEvidenceStore()
        self.uploaded_evidence_store = UploadedProfileEvidenceStore()
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.topic_store = TopicStore()
        self.memory_policy = MemoryClassificationPolicy()

    def _normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _same_meaning(self, a: str, b: str) -> bool:
        na = self._normalize_text(a)
        nb = self._normalize_text(b)
        if not na or not nb:
            return False
        return na == nb or na in nb or nb in na

    def _topic_label(self, topic: str | None, topic_id: str | None) -> str:
        if topic:
            return str(topic).strip() or "general"
        return self.topic_store.get_topic_summary(topic_id)

    def _load_topic_corrections(self, topic: str | None = None, topic_id: str | None = None) -> list[dict]:
        if hasattr(self.correction_store, "list_active_by_topic"):
            return self.correction_store.list_active_by_topic(topic=topic, topic_id=topic_id, limit=5)

        if hasattr(self.correction_store, "search"):
            query = topic or self.topic_store.get_topic_summary(topic_id)
            rows = self.correction_store.search(query, limit=5)
            filtered: list[dict] = []
            for row in rows:
                status = str(row.get("status") or "").lower()
                if not status or status == "active":
                    filtered.append(row)
            return filtered

        return []

    def _has_conflicting_active_correction(self, candidate_content: str, topic: str | None = None, topic_id: str | None = None) -> bool:
        active_corrections = self._load_topic_corrections(topic=topic, topic_id=topic_id)
        for correction in active_corrections:
            correction_content = str(correction.get("content") or "").strip()
            if not correction_content:
                continue
            if not self._same_meaning(correction_content, candidate_content):
                return True
        return False


    def _build_candidate_clusters(self, evidences: list[dict]) -> list[dict]:
        clusters: dict[tuple[str, str], dict] = {}

        for evidence in evidences:
            topic_id = str(evidence.get("topic_id") or "").strip() or None
            topic = self._topic_label(evidence.get("topic"), topic_id)
            candidate_content = (evidence.get("candidate_content") or "").strip()
            source_strength = (evidence.get("source_strength") or "").strip()

            if not candidate_content:
                continue

            classification = self.memory_policy.classify_evidence(evidence)
            if classification["route"] == "general":
                continue

            topic_key = topic_id or self._normalize_text(topic)
            key = (topic_key, self._normalize_text(candidate_content))

            if key not in clusters:
                clusters[key] = {
                    "topic": topic,
                    "topic_id": topic_id,
                    "candidate_content": candidate_content,
                    "evidence_ids": [],
                    "group_ids": set(),
                    "source_paths": set(),
                    "confidence_values": [],
                    "source_strength_counts": {
                        "explicit_self_statement": 0,
                        "repeated_behavior": 0,
                        "temporary_interest": 0,
                    },
                    "linked_profile_ids": set(),
                    "direct_confirm_count": 0,
                    "memory_value_hits": 0,
                }

            cluster = clusters[key]
            if not cluster.get("topic_id") and topic_id:
                cluster["topic_id"] = topic_id
            cluster["topic"] = self._topic_label(cluster.get("topic"), cluster.get("topic_id"))
            cluster["evidence_ids"].append(str(evidence.get("id") or ""))
            cluster["group_ids"].add(str(evidence.get("group_id") or ""))
            cluster["source_paths"].add(str(evidence.get("source_file_path") or ""))
            cluster["confidence_values"].append(float(evidence.get("confidence") or 0.0))
            cluster["source_strength_counts"][source_strength] = (
                cluster["source_strength_counts"].get(source_strength, 0) + 1
            )

            if classification["route"] == "confirmed":
                cluster["direct_confirm_count"] += 1
            cluster["memory_value_hits"] += len(classification["signals"])

            linked_profile_id = str(evidence.get("linked_profile_id") or "").strip()
            if linked_profile_id:
                cluster["linked_profile_ids"].add(linked_profile_id)

        result: list[dict] = []
        for cluster in clusters.values():
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
                    "candidate_content": cluster["candidate_content"],
                    "evidence_ids": cluster["evidence_ids"],
                    "evidence_count": len(cluster["evidence_ids"]),
                    "distinct_group_count": len([x for x in cluster["group_ids"] if x]),
                    "distinct_source_count": len([x for x in cluster["source_paths"] if x]),
                    "avg_confidence": sum(confidence_values) / len(confidence_values),
                    "max_confidence": max(confidence_values),
                    "primary_strength": primary_strength,
                    "explicit_count": source_strength_counts.get("explicit_self_statement", 0),
                    "repeated_count": source_strength_counts.get("repeated_behavior", 0),
                    "linked_profile_ids": cluster["linked_profile_ids"],
                    "direct_confirm_count": cluster["direct_confirm_count"],
                    "memory_value_hits": cluster["memory_value_hits"],
                }
            )

        result.sort(
            key=lambda item: (
                -SOURCE_STRENGTH_ORDER.get(item["primary_strength"], 0),
                -item["evidence_count"],
                -item["distinct_source_count"],
                -item["avg_confidence"],
                item["topic"],
            )
        )
        return result

    def _is_promotable_cluster(self, cluster: dict) -> tuple[bool, str]:
        return self.memory_policy.is_promotable_cluster(cluster)

    def _promotion_confidence(self, cluster: dict) -> float:
        return self.memory_policy.promotion_confidence(cluster)

    def _list_all_candidate_evidence(self) -> list[dict]:
        result: list[dict] = []

        for item in self.project_evidence_store.list_candidate_evidence():
            copied = dict(item)
            copied["group_id"] = copied.get("project_id")
            result.append(copied)

        for item in self.uploaded_evidence_store.list_candidate_evidence():
            copied = dict(item)
            copied["group_id"] = copied.get("source_id")
            result.append(copied)

        return result

    def _link_profile_for_candidate_across_stores(
        self,
        candidate_content: str,
        profile_id: str,
        topic_id: str | None = None,
        topic: str | None = None,
    ) -> int:
        linked = 0
        linked += self.project_evidence_store.link_profile_for_candidate(
            topic_id=topic_id,
            topic=topic,
            candidate_content=candidate_content,
            profile_id=profile_id,
        )
        linked += self.uploaded_evidence_store.link_profile_for_candidate(
            topic_id=topic_id,
            topic=topic,
            candidate_content=candidate_content,
            profile_id=profile_id,
        )
        return linked

    def _promote_confirmed_profiles(self) -> dict:
        evidences = self._list_all_candidate_evidence()
        clusters = self._build_candidate_clusters(evidences)

        promoted_profiles = 0
        linked_existing_profiles = 0
        blocked_by_correction = 0
        blocked_by_existing_profile_conflict = 0
        pending_candidates = 0

        for cluster in clusters:
            topic_id = cluster.get("topic_id")
            topic = cluster["topic"]
            candidate_content = cluster["candidate_content"]

            promotable, _reason = self._is_promotable_cluster(cluster)
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
                    linked_count = self._link_profile_for_candidate_across_stores(
                        candidate_content=candidate_content,
                        profile_id=active_profile["id"],
                        topic_id=active_profile.get("topic_id") or topic_id,
                        topic=topic,
                    )
                    if linked_count > 0:
                        linked_existing_profiles += 1
                    continue

                blocked_by_existing_profile_conflict += 1
                continue

            new_profile_id = self.profile_store.insert_profile(
                topic=topic,
                topic_id=topic_id,
                content=candidate_content,
                source=f"artifact_promotion_v1:{cluster['primary_strength']}",
                confidence=self._promotion_confidence(cluster),
            )
            self._link_profile_for_candidate_across_stores(
                candidate_content=candidate_content,
                profile_id=new_profile_id,
                topic_id=topic_id,
                topic=topic,
            )
            promoted_profiles += 1

        return {
            "promoted_profiles": promoted_profiles,
            "linked_existing_profiles": linked_existing_profiles,
            "blocked_by_correction": blocked_by_correction,
            "blocked_by_existing_profile_conflict": blocked_by_existing_profile_conflict,
            "pending_candidates": pending_candidates,
        }

    def _sync_evidences(self, evidences: list[dict], evidence_store) -> dict:
        processed = 0
        linked_to_existing_active_profile = 0
        skipped = 0

        for evidence in evidences:
            topic_id = str(evidence.get("topic_id") or "").strip() or None
            topic = self._topic_label(evidence.get("topic"), topic_id)
            candidate_content = (evidence.get("candidate_content") or "").strip()
            source_strength = (evidence.get("source_strength") or "").strip()

            if not candidate_content:
                evidence_store.mark_applied(evidence["id"])
                skipped += 1
                processed += 1
                continue

            classification = self.memory_policy.classify_evidence(evidence)
            if classification["route"] == "general":
                evidence_store.mark_applied(evidence["id"])
                skipped += 1
                processed += 1
                continue

            active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
            if active_profile and self._same_meaning(active_profile.get("content", ""), candidate_content):
                evidence_store.mark_applied(
                    evidence["id"],
                    linked_profile_id=active_profile["id"],
                )
                linked_to_existing_active_profile += 1
                processed += 1
                continue

            evidence_store.mark_applied(evidence["id"])
            processed += 1

        promotion_result = self._promote_confirmed_profiles()

        return {
            "processed": processed,
            "inserted_profiles": promotion_result["promoted_profiles"],
            "added_corrections": 0,
            "linked_to_existing_active_profile": linked_to_existing_active_profile,
            "promoted_profiles": promotion_result["promoted_profiles"],
            "linked_existing_profiles": promotion_result["linked_existing_profiles"],
            "blocked_by_correction": promotion_result["blocked_by_correction"],
            "blocked_by_existing_profile_conflict": promotion_result["blocked_by_existing_profile_conflict"],
            "pending_candidates": promotion_result["pending_candidates"],
            "skipped": skipped,
        }

    def sync_project(self, project_id: str) -> dict:
        evidences = self.project_evidence_store.list_unapplied_by_project(project_id)
        return self._sync_evidences(evidences=evidences, evidence_store=self.project_evidence_store)

    def sync_uploaded_source(self, source_id: str) -> dict:
        evidences = self.uploaded_evidence_store.list_unapplied_by_source(source_id)
        return self._sync_evidences(evidences=evidences, evidence_store=self.uploaded_evidence_store)
