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
    action types, source strength, confidence, and direct confirmation.
    """

    def normalize_source_strength(self, value: object | None) -> str:
        text = str(value or "").strip()
        return text if text in SOURCE_STRENGTH_ORDER else ""

    def _bounded_confidence(self, value: object | None) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.0
        return min(max(score, 0.0), 1.0)

    def _signal_tags_from_evidence(self, evidence: dict) -> list[str]:
        tags: list[str] = []
        strength = self.normalize_source_strength(evidence.get("source_strength"))
        if strength:
            tags.append(f"source_strength:{strength}")
        if bool(evidence.get("direct_confirm")):
            tags.append("direct_confirm")
        return tags

    def classify_chat_memory(
        self,
        action_types: set[str] | None = None,
        similarity: float = 0.0,
        source_strength: str | None = None,
        direct_confirm: bool = False,
        confidence: object | None = None,
    ) -> dict:
        _ = similarity
        action_types = action_types or set()
        meaningful_actions = {a for a in action_types if a and a != "discard"}
        if not meaningful_actions:
            return {"route": "discard", "signals": [], "confidence": 0.0}

        normalized_strength = self.normalize_source_strength(source_strength)
        resolved_confidence = self._bounded_confidence(confidence)

        signals = [f"action:{a}" for a in sorted(meaningful_actions)]
        if normalized_strength:
            signals.append(f"source_strength:{normalized_strength}")
        if direct_confirm:
            signals.append("direct_confirm")

        if direct_confirm and resolved_confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "confirmed", "signals": signals, "confidence": resolved_confidence}
        if normalized_strength == "explicit_self_statement" and resolved_confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "candidate", "signals": signals, "confidence": resolved_confidence}
        if normalized_strength == "repeated_behavior" and resolved_confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "candidate", "signals": signals, "confidence": resolved_confidence}

        return {
            "route": "general",
            "signals": signals,
            "confidence": resolved_confidence,
        }

    def classify_evidence(self, evidence: dict) -> dict:
        candidate_content = str(evidence.get("candidate_content") or "").strip()
        if not candidate_content:
            return {"route": "discard", "signals": []}

        strength = self.normalize_source_strength(evidence.get("source_strength"))
        confidence = self._bounded_confidence(evidence.get("confidence"))
        direct_confirm = bool(evidence.get("direct_confirm"))
        signals = self._signal_tags_from_evidence(evidence)

        if direct_confirm and confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "confirmed", "signals": signals}
        if strength == "explicit_self_statement" and confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "candidate", "signals": signals}
        if strength == "repeated_behavior" and confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "candidate", "signals": signals}
        if strength == "temporary_interest":
            return {"route": "general", "signals": signals}

        return {"route": "general", "signals": signals}

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
            return True, "promotable_single_high_value_candidate"

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
