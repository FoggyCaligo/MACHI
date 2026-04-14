from __future__ import annotations

from config import PROFILE_SEMANTIC_CLUSTER_THRESHOLD, PROFILE_SEMANTIC_MATCH_THRESHOLD
from tools.text_embedding import cosine_similarity, embed_text


class ProfileEvidenceGraph:
    def __init__(self, *, topic_store=None) -> None:
        self.topic_store = topic_store
        self._embedding_cache: dict[str, list[float]] = {}

    def normalize_text(self, text: str | None) -> str:
        return " ".join((text or "").strip().split())

    def clip_text(self, text: str | None, max_len: int = 360) -> str:
        normalized = self.normalize_text(text)
        if not normalized:
            return ""
        if len(normalized) > max_len:
            return normalized[:max_len].rstrip() + "..."
        return normalized

    def content_embedding(self, text: str | None) -> list[float]:
        normalized = self.normalize_text(text)
        if not normalized:
            return []
        if normalized not in self._embedding_cache:
            self._embedding_cache[normalized] = embed_text(normalized, kind="passage")
        return self._embedding_cache[normalized]

    def semantic_similarity(self, left: str | None, right: str | None) -> float:
        left_embedding = self.content_embedding(left)
        right_embedding = self.content_embedding(right)
        return cosine_similarity(left_embedding, right_embedding)

    def same_meaning(
        self,
        left: str | None,
        right: str | None,
        *,
        threshold: float = PROFILE_SEMANTIC_MATCH_THRESHOLD,
    ) -> bool:
        normalized_left = self.normalize_text(left)
        normalized_right = self.normalize_text(right)
        if not normalized_left or not normalized_right:
            return False
        if normalized_left == normalized_right:
            return True
        return self.semantic_similarity(normalized_left, normalized_right) >= threshold

    def topic_label(self, topic: str | None = None, topic_id: str | None = None) -> str:
        if topic:
            return str(topic).strip() or "general"
        if topic_id and self.topic_store is not None:
            topic_row = self.topic_store.get_topic(topic_id)
            if topic_row:
                return str(topic_row.get("summary") or topic_row.get("name") or "general").strip() or "general"
        return "general"

    def topic_key(
        self,
        *,
        item: dict | None = None,
        topic: str | None = None,
        topic_id: str | None = None,
    ) -> str | None:
        if item is not None:
            topic = item.get("topic")
            topic_id = str(item.get("topic_id") or "").strip() or None

        if topic_id:
            return f"id:{topic_id}"

        normalized_topic = self.normalize_text(topic)
        if normalized_topic and normalized_topic.lower() != "general":
            return f"topic:{normalized_topic.lower()}"
        return None

    def primary_strength(self, source_strength_counts: dict[str, int] | None) -> str:
        counts = source_strength_counts or {}
        if counts.get("explicit_self_statement", 0) > 0:
            return "explicit_self_statement"
        if counts.get("repeated_behavior", 0) > 0:
            return "repeated_behavior"
        if counts.get("temporary_interest", 0) > 0:
            return "temporary_interest"
        return ""

    def source_strength_from_profile_source(self, source: str | None, *, memory_policy) -> str:
        text = str(source or "").strip()
        if text.startswith("evidence_promotion:"):
            candidate = text.split(":", 1)[1].strip()
            return memory_policy.normalize_source_strength(candidate)
        if text.startswith("direct_confirm:") or text == "chat_direct_confirm":
            return "explicit_self_statement"
        return ""

    def build_candidate_clusters(
        self,
        evidences: list[dict],
        *,
        memory_policy,
        source_strength_order: dict[str, int],
        semantic_cluster_threshold: float = PROFILE_SEMANTIC_CLUSTER_THRESHOLD,
    ) -> list[dict]:
        clusters: list[dict] = []

        for evidence in evidences:
            topic_id = str(evidence.get("topic_id") or "").strip() or None
            topic = self.topic_label(topic=evidence.get("topic"), topic_id=topic_id)
            candidate_content = str(evidence.get("candidate_content") or "").strip()
            source_strength = str(evidence.get("source_strength") or "").strip()
            memory_tier = (
                memory_policy.normalize_memory_tier(evidence.get("memory_tier"))
                or memory_policy.classify_evidence(evidence)["route"]
            )

            if not candidate_content or memory_tier == "discard":
                continue

            topic_key = self.topic_key(topic=topic, topic_id=topic_id) or "general"
            matched_cluster = None
            best_similarity = 0.0

            for cluster in clusters:
                if cluster["topic_key"] != topic_key:
                    continue
                similarity = self.semantic_similarity(candidate_content, cluster["representative_content"])
                if similarity >= semantic_cluster_threshold and similarity > best_similarity:
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
            cluster["topic"] = self.topic_label(topic=cluster.get("topic"), topic_id=cluster.get("topic_id"))
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
            result.append(
                {
                    "topic": cluster["topic"],
                    "topic_id": cluster.get("topic_id"),
                    "candidate_content": cluster["representative_content"],
                    "evidence_ids": cluster["evidence_ids"],
                    "evidence_rows": cluster["evidence_rows"],
                    "evidence_count": len(cluster["evidence_ids"]),
                    "distinct_group_count": len([value for value in cluster["group_ids"] if value]),
                    "distinct_source_count": len([value for value in cluster["source_paths"] if value]),
                    "avg_confidence": sum(confidence_values) / len(confidence_values),
                    "max_confidence": max(confidence_values),
                    "primary_strength": self.primary_strength(cluster["source_strength_counts"]),
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
                -source_strength_order.get(item["primary_strength"], 0),
                -item["distinct_group_count"],
                -item["evidence_count"],
                -item["avg_confidence"],
                item["topic"],
            )
        )
        return result

    def build_profile_support_index(self, evidences: list[dict], *, memory_policy) -> dict[str, dict]:
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

            strength = memory_policy.normalize_source_strength(evidence.get("source_strength"))
            if strength:
                row["source_strength_counts"][strength] = row["source_strength_counts"].get(strength, 0) + 1

            tier = memory_policy.normalize_memory_tier(evidence.get("memory_tier"))
            if tier == "confirmed":
                row["confirmed_count"] += 1
            if bool(evidence.get("direct_confirm")):
                row["direct_confirm_count"] += 1

        result: dict[str, dict] = {}
        for profile_id, row in grouped.items():
            confidence_values = row["confidence_values"] or [0.0]
            result[profile_id] = {
                "distinct_group_count": len([value for value in row["group_ids"] if value]),
                "avg_confidence": sum(confidence_values) / len(confidence_values),
                "max_confidence": max(confidence_values),
                "primary_strength": self.primary_strength(row["source_strength_counts"]),
                "direct_confirm_count": row["direct_confirm_count"],
                "confirmed_count": row["confirmed_count"],
                "evidence_count": row["evidence_count"],
            }
        return result

    def profile_support_snapshot(
        self,
        active_profile: dict,
        support_index: dict[str, dict],
        *,
        memory_policy,
    ) -> dict:
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
            "primary_strength": self.source_strength_from_profile_source(source, memory_policy=memory_policy),
            "direct_confirm_count": direct_confirm,
            "confirmed_count": direct_confirm,
            "evidence_count": 1,
        }

    def support_score(self, snapshot: dict, *, source_strength_order: dict[str, int]) -> float:
        score = max(float(snapshot.get("avg_confidence") or 0.0), float(snapshot.get("max_confidence") or 0.0))
        score += 0.08 * min(int(snapshot.get("distinct_group_count") or 0), 3)
        score += 0.03 * min(max(int(snapshot.get("evidence_count") or 0) - 1, 0), 3)
        score += 0.08 * source_strength_order.get(str(snapshot.get("primary_strength") or ""), 0)
        if int(snapshot.get("confirmed_count") or 0) > 0:
            score += 0.20
        if int(snapshot.get("direct_confirm_count") or 0) > 0:
            score += 0.25
        return score

    def dedupe_ranked_rows(self, ranked_rows: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen_keys: set[str] = set()

        for row in ranked_rows or []:
            lookup_key = str(row.get("lookup_key") or row.get("_lookup_key") or row.get("id") or "").strip()
            if not lookup_key or lookup_key in seen_keys:
                continue
            seen_keys.add(lookup_key)
            deduped.append(row)

        return deduped

    def _reference_key(self, item: dict) -> str:
        return str(item.get("_lookup_key") or item.get("lookup_key") or item.get("source_id") or item.get("id") or "").strip()

    def build_reference_trace(
        self,
        *,
        reference: dict,
        references: list[dict],
        ranked_rows: list[dict],
        active_topic_id: str | None = None,
    ) -> dict | None:
        topic_key = self.topic_key(item=reference)
        active_topic_match = bool(active_topic_id and str(reference.get("topic_id") or "").strip() == active_topic_id)
        reference_candidate = self.normalize_text(reference.get("candidate_content"))

        topic_support_count = 0
        candidate_support_count = 0
        for row in ranked_rows:
            if topic_key and self.topic_key(item=row) == topic_key:
                topic_support_count += 1
            if reference_candidate and self.same_meaning(reference_candidate, row.get("candidate_content")):
                candidate_support_count += 1

        reference_key = self._reference_key(reference)
        connections: list[dict] = []
        for other in references:
            if self._reference_key(other) == reference_key:
                continue

            via: list[str] = []
            if topic_key and self.topic_key(item=other) == topic_key:
                via.append("same_topic")
            if reference_candidate and self.same_meaning(reference_candidate, other.get("candidate_content")):
                via.append("same_candidate_meaning")

            if not via:
                continue

            connections.append(
                {
                    "label": self.normalize_text(other.get("label")) or self.normalize_text(other.get("source_kind")) or "source",
                    "source_kind": self.normalize_text(other.get("source_kind")) or None,
                    "topic": self.normalize_text(other.get("topic")) or None,
                    "candidate_content": self.clip_text(other.get("candidate_content"), max_len=120) or None,
                    "via": via,
                }
            )

        connections.sort(
            key=lambda item: (
                len(item.get("via") or []),
                item.get("label") or "",
            ),
            reverse=True,
        )

        if not active_topic_match and topic_support_count <= 1 and candidate_support_count <= 1 and not connections:
            return None

        return {
            "topic_anchor": self.normalize_text(reference.get("topic")) or None,
            "active_topic_match": active_topic_match,
            "topic_support_count": topic_support_count,
            "candidate_support_count": candidate_support_count,
            "connections": connections[:2],
        }

    def attach_reference_traces(
        self,
        references: list[dict],
        ranked_rows: list[dict],
        *,
        active_topic_id: str | None = None,
    ) -> list[dict]:
        if not references:
            return []

        deduped_ranked_rows = self.dedupe_ranked_rows(ranked_rows)
        traced: list[dict] = []

        for reference in references:
            enriched = dict(reference)
            trace = self.build_reference_trace(
                reference=enriched,
                references=references,
                ranked_rows=deduped_ranked_rows,
                active_topic_id=active_topic_id,
            )
            if trace:
                enriched["trace"] = trace
            cleaned = {
                key: value
                for key, value in enriched.items()
                if not str(key).startswith("_")
            }
            traced.append(cleaned)

        return traced
