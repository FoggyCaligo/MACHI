import re

from config import TOPIC_CONFIRM_MIN_CONFIDENCE


SOURCE_STRENGTH_ORDER = {
    "temporary_interest": 1,
    "repeated_behavior": 2,
    "explicit_self_statement": 3,
}

FIRST_PERSON_ASSERTION_PATTERNS = (
    r"(?:나는|난|내가|내 성향은|저는|제가).*(?:이다|다|한다|원한다|싫다|좋다|중요하다|필요하다)",
    r"(?:나는|난|저는).*(?:사람|편)이다",
)
STRONG_CONFIDENCE_MARKERS = ("확실", "분명", "무조건", "반드시", "정말", "틀림없이", "확신")
CONCRETE_BACKGROUND_MARKERS = ("어릴", "예전", "최근", "지금", "학교", "회사", "가족", "관계", "프로젝트", "작업")


class MemoryClassificationPolicy:
    def normalize_text(self, text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def normalize_source_strength(self, value: str | None) -> str:
        text = str(value or "").strip()
        if text in SOURCE_STRENGTH_ORDER:
            return text
        return "repeated_behavior"

    def has_first_person_assertion(self, text: str) -> bool:
        compact = self.normalize_text(text)
        return any(re.search(pattern, compact) for pattern in FIRST_PERSON_ASSERTION_PATTERNS)

    def has_strong_confidence(self, text: str) -> bool:
        return any(marker in (text or "") for marker in STRONG_CONFIDENCE_MARKERS)

    def has_concrete_background(self, text: str) -> bool:
        text = text or ""
        if any(marker in text for marker in CONCRETE_BACKGROUND_MARKERS):
            return True
        return bool(re.search(r"(?:19|20)\d{2}", text))

    def message_memory_signals(self, user_message: str, action_types: set[str] | None = None) -> list[str]:
        action_types = action_types or set()
        signals: list[str] = []
        if self.has_first_person_assertion(user_message):
            signals.append("first_person_assertion")
        if "new_correction" in action_types:
            signals.append("repeated_or_explicit_correction")
        if self.has_strong_confidence(user_message):
            signals.append("strong_confidence")
        if self.has_concrete_background(user_message):
            signals.append("concrete_background")
        return signals

    def evidence_memory_signals(self, evidence: dict) -> list[str]:
        candidate_content = str(evidence.get("candidate_content") or "").strip()
        evidence_text = str(evidence.get("evidence_text") or "").strip()
        combined = f"{candidate_content}\n{evidence_text}".strip()
        signals: list[str] = []
        if self.normalize_source_strength(evidence.get("source_strength")) == "explicit_self_statement":
            signals.append("explicit_self_statement")
        if self.has_first_person_assertion(combined):
            signals.append("first_person_assertion")
        if self.has_strong_confidence(combined):
            signals.append("strong_confidence")
        if self.has_concrete_background(combined):
            signals.append("concrete_background")
        return signals

    def estimate_message_profile_confidence(self, signals: list[str], similarity: float) -> float:
        base = 0.72
        bonus = min(len(signals), 3) * 0.08
        return min(0.98, max(TOPIC_CONFIRM_MIN_CONFIDENCE, base + bonus + max(0.0, similarity - 0.7) * 0.2))

    def is_direct_confirmable_evidence(self, evidence: dict) -> bool:
        confidence = float(evidence.get("confidence") or 0.0)
        if confidence < TOPIC_CONFIRM_MIN_CONFIDENCE:
            return False
        return bool(self.evidence_memory_signals(evidence))

    def classify_chat_memory(self, user_message: str, action_types: set[str] | None = None, similarity: float = 0.0) -> dict:
        signals = self.message_memory_signals(user_message, action_types)
        if signals:
            return {
                "route": "confirmed",
                "signals": signals,
                "confidence": self.estimate_message_profile_confidence(signals, similarity),
            }
        cleaned = (user_message or "").strip()
        if len(cleaned) >= 20:
            return {"route": "general", "signals": [], "confidence": 0.0}
        return {"route": "discard", "signals": [], "confidence": 0.0}

    def classify_evidence(self, evidence: dict) -> dict:
        candidate_content = str(evidence.get("candidate_content") or "").strip()
        if not candidate_content:
            return {"route": "discard", "signals": []}
        if self.is_direct_confirmable_evidence(evidence):
            return {"route": "confirmed", "signals": self.evidence_memory_signals(evidence)}
        strength = self.normalize_source_strength(evidence.get("source_strength"))
        if strength == "temporary_interest":
            return {"route": "general", "signals": self.evidence_memory_signals(evidence)}
        return {"route": "candidate", "signals": self.evidence_memory_signals(evidence)}

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
