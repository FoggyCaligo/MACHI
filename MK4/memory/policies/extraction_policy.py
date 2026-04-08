import re
from dataclasses import dataclass

TOPIC_RULES = {
    "response_style": ["구조", "설명", "검증", "위로", "칭찬", "need", "want", "논리"],
    "reasoning_style": ["가설", "논리", "검증", "전제", "구조"],
    "project_context": ["mk4", "mk3", "gemma", "ollama", "sqlite", "프로젝트"],
    "emotional_support": ["위로", "감정", "불안", "안정"],
}

STATE_RULES = {
    "current_mood": ["기분", "불안", "우울", "답답", "편안", "지침", "스트레스"],
}


def infer_topic(text: str) -> str:
    lowered = text.lower()
    for topic, keywords in TOPIC_RULES.items():
        if any(k in lowered or k in text for k in keywords):
            return topic
    return "general"


class ExtractionPolicy:
    def extract(self, user_message: str, reply: str, update_plan: dict) -> dict:
        topic = infer_topic(user_message)
        result = {
            "profiles": [],
            "corrections": [],
            "episodes": [],
            "states": [],
            "discarded": [],
        }

        action_types = {a["type"] for a in update_plan.get("actions", [])}

        explicit_correction = any(token in user_message for token in ["정정", "정확히는", "맞긴 해", "핵심은", "다만"])
        if explicit_correction or "new_correction" in action_types:
            result["corrections"].append({
                "topic": topic,
                "content": user_message.strip(),
                "reason": "explicit_correction_or_conflict_candidate",
                "source": "user_explicit",
            })

        for state_key, hints in STATE_RULES.items():
            if any(h in user_message for h in hints):
                result["states"].append({
                    "key": state_key,
                    "value": user_message.strip(),
                    "source": "user_explicit",
                })
                break

        if len(user_message.strip()) >= 20:
            result["episodes"].append({
                "topic": topic,
                "summary": user_message.strip()[:300],
                "raw_ref": user_message.strip(),
                "importance": 0.6 if explicit_correction else 0.4,
            })
        else:
            result["discarded"].append(user_message.strip())

        return result
