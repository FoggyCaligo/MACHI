from config import TOPIC_CONFIRM_MIN_CONFIDENCE


SOURCE_STRENGTH_ORDER = {
    "temporary_interest": 1,
    "repeated_behavior": 2,
    "explicit_self_statement": 3,
}


MIN_SIGNAL_CONFIDENCE = 0.25
SINGLE_HIGH_VALUE_PROMOTION_CONFIDENCE = 0.9
REPEAT_PROMOTION_MIN_AVG_CONFIDENCE = 0.35
PROMOTION_MIN_EVIDENCE_COUNT = 2


class MemoryClassificationPolicy:
    """Apply route/promotion policy to already-structured signals only.

    This layer must not interpret raw language. It consumes structured inputs
    produced upstream and applies threshold-based routing policy.
    """

    def normalize_source_strength(self, value: str | None) -> str:
        text = str(value or "").strip()
        return text if text in SOURCE_STRENGTH_ORDER else ""

    def normalize_memory_tier(self, value: str | None) -> str:
        text = str(value or "").strip().lower()
        return text if text in {"general", "candidate", "confirmed"} else ""

    def _bounded_confidence(self, value: float | None) -> float:
        if value is None:
            return 0.0
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
        tier = self.normalize_memory_tier(evidence.get("memory_tier"))
        if tier:
            tags.append(f"memory_tier:{tier}")
        if bool(evidence.get("direct_confirm")):
            tags.append("direct_confirm")
        return tags

    def classify_chat_memory(
        self,
        action_types: set[str] | None = None,
        similarity: float = 0.0,
        source_strength: str | None = None,
        direct_candidate: bool = False,
        direct_confirm: bool = False,
        confidence: float | None = None,
        memory_tier: str | None = None,
    ) -> dict:
        _ = similarity
        action_types = action_types or set()
        meaningful_actions = {a for a in action_types if a and a != "discard"}
        if "profile_candidate" not in meaningful_actions:
            return {"route": "discard", "signals": [], "confidence": 0.0}

        normalized_strength = self.normalize_source_strength(source_strength)
        resolved_confidence = self._bounded_confidence(confidence)
        normalized_tier = self.normalize_memory_tier(memory_tier)

        signals = [f"action:{a}" for a in sorted(meaningful_actions)]
        if normalized_strength:
            signals.append(f"source_strength:{normalized_strength}")
        if direct_candidate:
            signals.append("direct_candidate")
        if direct_confirm:
            signals.append("direct_confirm")
        if normalized_tier:
            signals.append(f"memory_tier:{normalized_tier}")

        if normalized_tier:
            return {"route": normalized_tier, "signals": signals, "confidence": resolved_confidence}
        if direct_confirm and resolved_confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "confirmed", "signals": signals, "confidence": resolved_confidence}
        if normalized_strength and resolved_confidence >= MIN_SIGNAL_CONFIDENCE:
            return {"route": "candidate", "signals": signals, "confidence": resolved_confidence}
        return {"route": "general", "signals": signals, "confidence": resolved_confidence}

    def classify_evidence(self, evidence: dict) -> dict:
        candidate_content = str(evidence.get("candidate_content") or "").strip()
        if not candidate_content:
            return {"route": "discard", "signals": []}

        strength = self.normalize_source_strength(evidence.get("source_strength"))
        confidence = self._bounded_confidence(evidence.get("confidence"))
        direct_confirm = bool(evidence.get("direct_confirm"))
        normalized_tier = self.normalize_memory_tier(evidence.get("memory_tier"))
        signals = self._signal_tags_from_evidence(evidence)

        if normalized_tier:
            return {"route": normalized_tier, "signals": signals}
        if direct_confirm and confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return {"route": "confirmed", "signals": signals}
        if strength and confidence >= MIN_SIGNAL_CONFIDENCE:
            return {"route": "candidate", "signals": signals}
        return {"route": "general", "signals": signals}

    def is_promotable_cluster(self, cluster: dict) -> tuple[bool, str]:
        distinct_group_count = int(cluster.get("distinct_group_count") or 0)
        avg_confidence = self._bounded_confidence(cluster.get("avg_confidence"))
        max_confidence = self._bounded_confidence(cluster.get("max_confidence"))
        direct_confirm_count = int(cluster.get("direct_confirm_count") or 0)
        confirmed_count = int(cluster.get("confirmed_count") or 0)

        if direct_confirm_count > 0 and max_confidence >= TOPIC_CONFIRM_MIN_CONFIDENCE:
            return True, "promotable_direct_confirm"
        if confirmed_count > 0:
            return True, "promotable_confirmed_tier"
        if max_confidence >= SINGLE_HIGH_VALUE_PROMOTION_CONFIDENCE:
            return True, "promotable_single_high_confidence"
        if distinct_group_count >= PROMOTION_MIN_EVIDENCE_COUNT and avg_confidence >= REPEAT_PROMOTION_MIN_AVG_CONFIDENCE:
            return True, "promotable_repeated_signal"
        return False, "not_enough_signal"

    def promotion_confidence(self, cluster: dict) -> float:
        avg_confidence = self._bounded_confidence(cluster.get("avg_confidence"))
        max_confidence = self._bounded_confidence(cluster.get("max_confidence"))
        distinct_group_count = int(cluster.get("distinct_group_count") or 0)
        direct_confirm_count = int(cluster.get("direct_confirm_count") or 0)
        confirmed_count = int(cluster.get("confirmed_count") or 0)

        boosted = max(avg_confidence, max_confidence)
        if distinct_group_count >= PROMOTION_MIN_EVIDENCE_COUNT:
            boosted += 0.05
        if direct_confirm_count > 0 or confirmed_count > 0:
            boosted = max(boosted, TOPIC_CONFIRM_MIN_CONFIDENCE)
        return min(max(boosted, 0.45), 0.98)
