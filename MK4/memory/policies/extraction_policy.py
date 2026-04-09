import re

from config import TOPIC_CONFIRM_MIN_CONFIDENCE
from memory.services.topic_router import TopicRouter


FIRST_PERSON_ASSERTION_PATTERNS = (
    r"(?:나는|난|내가|내 성향은|저는|제가).*(?:이다|다|한다|원한다|싫다|좋다|중요하다|필요하다)",
    r"(?:나는|난|저는).*(?:사람|편)이다",
)

STRONG_CONFIDENCE_MARKERS = (
    "확실", "분명", "무조건", "반드시", "정말", "틀림없이", "확신",
)

CONCRETE_BACKGROUND_MARKERS = (
    "어릴", "예전", "최근", "지금", "학교", "회사", "가족", "관계", "프로젝트", "작업",
)

STATE_RULES = {
    "current_mood": ["기분", "불안", "우울", "답답", "편안", "지침", "스트레스"],
}


class ExtractionPolicy:
    def __init__(self) -> None:
        self.topic_router = TopicRouter()

    def _is_explicit_correction(self, user_message: str, action_types: set[str]) -> bool:
        correction_tokens = ("정정", "정확히는", "맞긴 해", "핵심은", "다만")
        return any(token in user_message for token in correction_tokens) or "new_correction" in action_types

    def _has_first_person_assertion(self, user_message: str) -> bool:
        compact = " ".join((user_message or "").strip().split())
        return any(re.search(pattern, compact) for pattern in FIRST_PERSON_ASSERTION_PATTERNS)

    def _has_strong_confidence(self, user_message: str) -> bool:
        return any(marker in user_message for marker in STRONG_CONFIDENCE_MARKERS)

    def _has_concrete_background(self, user_message: str) -> bool:
        if any(marker in user_message for marker in CONCRETE_BACKGROUND_MARKERS):
            return True
        return bool(re.search(r"(?:19|20)\d{2}", user_message))

    def _memory_value_signals(self, user_message: str, action_types: set[str]) -> list[str]:
        signals: list[str] = []
        if self._has_first_person_assertion(user_message):
            signals.append("first_person_assertion")
        if "new_correction" in action_types:
            signals.append("repeated_or_explicit_correction")
        if self._has_strong_confidence(user_message):
            signals.append("strong_confidence")
        if self._has_concrete_background(user_message):
            signals.append("concrete_background")
        return signals

    def _estimate_profile_confidence(self, signals: list[str], similarity: float) -> float:
        base = 0.72
        bonus = min(len(signals), 3) * 0.08
        return min(0.98, max(TOPIC_CONFIRM_MIN_CONFIDENCE, base + bonus + max(0.0, similarity - 0.7) * 0.2))

    def extract(self, user_message: str, reply: str, update_plan: dict, model: str | None = None) -> dict:
        topic_resolution = self.topic_router.resolve(user_message=user_message, model=model)
        topic = topic_resolution.topic_summary or "general"
        topic_id = topic_resolution.topic_id

        result = {
            "profiles": [],
            "corrections": [],
            "episodes": [],
            "states": [],
            "discarded": [],
            "topic_resolution": {
                "decision": topic_resolution.decision,
                "topic_id": topic_id,
                "topic": topic,
                "similarity": topic_resolution.similarity,
                "used_active_topic": topic_resolution.used_active_topic,
            },
        }

        action_types = {a["type"] for a in update_plan.get("actions", [])}
        explicit_correction = self._is_explicit_correction(user_message, action_types)
        memory_signals = self._memory_value_signals(user_message, action_types)
        high_memory_value = bool(memory_signals)

        if explicit_correction:
            result["corrections"].append({
                "topic_id": topic_id,
                "topic": topic,
                "content": user_message.strip(),
                "reason": "explicit_correction_or_conflict_candidate",
                "source": "user_explicit",
            })

        if high_memory_value and not explicit_correction:
            result["profiles"].append({
                "topic_id": topic_id,
                "topic": topic,
                "content": user_message.strip(),
                "source": "user_explicit_high_value",
                "confidence": self._estimate_profile_confidence(memory_signals, topic_resolution.similarity),
                "signals": memory_signals,
            })

        for state_key, hints in STATE_RULES.items():
            if any(h in user_message for h in hints):
                result["states"].append({
                    "key": state_key,
                    "value": user_message.strip(),
                    "source": "user_explicit",
                })
                break

        result["states"].append({
            "key": "active_topic_id",
            "value": topic_id or "",
            "source": "topic_router",
        })
        result["states"].append({
            "key": "active_topic_summary",
            "value": topic,
            "source": "topic_router",
        })

        cleaned = user_message.strip()
        if len(cleaned) >= 20:
            result["episodes"].append({
                "topic_id": topic_id,
                "topic": topic,
                "summary": cleaned[:300],
                "raw_ref": cleaned,
                "importance": 0.8 if high_memory_value or explicit_correction else 0.4,
            })
        else:
            result["discarded"].append(cleaned)

        return result
