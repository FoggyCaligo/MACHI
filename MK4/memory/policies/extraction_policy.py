from memory.policies.memory_classification_policy import MemoryClassificationPolicy
from memory.services.topic_router import TopicRouter


STATE_RULES = {
    "current_mood": ["기분", "불안", "우울", "답답", "편안", "지침", "스트레스"],
}


class ExtractionPolicy:
    def __init__(self) -> None:
        self.topic_router = TopicRouter()
        self.memory_policy = MemoryClassificationPolicy()

    def _is_explicit_correction(self, user_message: str, action_types: set[str]) -> bool:
        correction_tokens = ("정정", "정확히는", "맞긴 해", "핵심은", "다만")
        return any(token in user_message for token in correction_tokens) or "new_correction" in action_types

    def extract(self, user_message: str, reply: str, update_plan: dict, model: str | None = None) -> dict:       
        topic_resolution = self.topic_router.resolve(
            user_message=user_message,
            model=model,
            use_active_topic=True,
            persist_active=True,
        )
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
        classification = self.memory_policy.classify_chat_memory(
            user_message=user_message,
            action_types=action_types,
            similarity=topic_resolution.similarity,
        )
        high_memory_value = classification["route"] == "confirmed"

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
                "confidence": classification["confidence"],
                "signals": classification["signals"],
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
                "memory_classification": classification["route"],
            })
        else:
            result["discarded"].append(cleaned)

        return result
