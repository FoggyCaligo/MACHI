from config import TOPIC_CONFIRM_MIN_CONFIDENCE


SOURCE_STRENGTH_ORDER = {
    "temporary_interest": 1,
    "repeated_behavior": 2,
    "explicit_self_statement": 3,
}


class MemoryClassificationPolicy:
    """Apply routing / promotion policy to already-structured upstream signals.

    This layer should not interpret raw language with regex/keyword heuristics.
    Upstream components are responsible for producing structured signals such as
    action types, source strength, and confidence.
    """

    def normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def normalize_source_strength(self, value: str | None) -> str:
        text = str(value or "").strip()
        if text in SOURCE_STRENGTH_ORDER:
            return text
        return "repeated_behavior"

    def _signal_tags_from_evidence(self, evidence: dict) -> list[str]:
        tags: list[str] = []
        strength = self.normalize_source_strength(evidence.get("source_strength"))
        if strength:
            tags.append(f"source_strength:{strength}")
        if bool(evidence.get("direct_confirm")):
            tags.append("direct_confirm")
        return tags

    def estimate_message_profile_confidence(self, similarity: float) -> float:
        base = TOPIC_CONFIRM_MIN_CONFIDENCE
        if similarity <= 0.0:
            return base
        return min(0.95, max(base, base + max(0.0, similarity - 0.7) * 0.2))

    def is_direct_confirmable_evidence(self, evidence: dict) -> bool:
        confidence = float(evidence.get("confidence") or 0.0)
        if confidence < TOPIC_CONFIRM_MIN_CONFIDENCE:
            return False
        if bool(evidence.get("direct_confirm")):
            return True
        return self.normalize_source_strength(evidence.get("source_strength")) == "explicit_self_statement"

    def classify_chat_memory(self, user_message: str, action_types: set[str] | None = None, similarity: float = 0.0) -> dict:
        action_types = action_types or set()
        cleaned = (user_message or "").strip()
        if not cleaned:
            return {"route": "discard", "signals": [], "confidence": 0.0}

        # explicit correction is handled separately in ExtractionPolicy.
        if action_types == {"discard"}:
            return {"route": "discard", "signals": [], "confidence": 0.0}

        if len(cleaned) < 20:
            return {"route": "discard", "signals": [], "confidence": 0.0}

        # Until an upstream structured memory-value classifier is added,
        # chat messages default to general memory rather than policy-side linguistic inference.
        return {
            "route": "general",
            "signals": [f"action:{a}" for a in sorted(action_types) if a != "discard"],
            "confidence": self.estimate_message_profile_confidence(similarity),
        }

    def classify_evidence(self, evidence: dict) -> dict:
        candidate_content = str(evidence.get("candidate_content") or "").strip()
        if not candidate_content:
            return {"route": "discard", "signals": []}

        strength = self.normalize_source_strength(evidence.get("source_strength"))
        signals = self._signal_tags_from_evidence(evidence)

        if self.is_direct_confirmable_evidence(evidence):
            return {"route": "confirmed", "signals": signals}

        if strength == "temporary_interest":
            return {"route": "general", "signals": signals}

        return {"route": "candidate", "signals": signals}

    def is_promotable_cluster(self, cluster: dict) -> tuple[bool, str]:
        evidence_count = int(cluster.get("evidence_count") or 0)
        distinct_group_count = int(cluster.get("distinct_group_count") or cluster.get("distinct_project_count") or 0)
        distinct_source_count = int(cluster.get("distinct_source_count") or 0)
        avg_confidence = float(cluster.get("avg_confidence") or 0.0)
        max_confidence = float(cluster.get("max_confidence") or 0.0)
        primary_strength = self.normalize_source_strength(cluster.get("primary_strength"))
        direct_confirm_count = int(cluster.get("direct_confirm_count") or 0)

        diversity_ok = distinct_source_count >= 2 or distinct_group_count >= 2

        if direct_confirm_count > 0 and max_confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return True, "promotable_single_high_value"

        if primary_strength == "explicit_self_statement":
            if evidence_count < 2:
                return False, "not_enough_repetition"
            if not diversity_ok:
                return False, "not_enough_source_diversity"
            if avg_confidence < 0.55:
                return False, "low_confidence"
            return True, "promotable_explicit"

        if evidence_count < 3:
            return False, "not_enough_repetition"
        if not diversity_ok:
            return False, "not_enough_source_diversity"
        if avg_confidence < 0.60:
            return False, "low_confidence"
        return True, "promotable_repeated"

    def promotion_confidence(self, cluster: dict) -> float:
        avg_confidence = float(cluster.get("avg_confidence") or 0.0)
        evidence_count = int(cluster.get("evidence_count") or 0)
        primary_strength = self.normalize_source_strength(cluster.get("primary_strength"))
        direct_confirm_count = int(cluster.get("direct_confirm_count") or 0)

        boosted = avg_confidence
        if primary_strength == "explicit_self_statement":
            boosted += 0.10
        if evidence_count >= 4:
            boosted += 0.05
        if direct_confirm_count > 0:
            boosted = max(boosted, TOPIC_CONFIRM_MIN_CONFIDENCE + 0.05)
        return min(max(boosted, 0.45), 0.95)
