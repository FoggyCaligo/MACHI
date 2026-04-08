import re

STATE_HINTS = {
    "current_mood": ["기분", "우울", "불안", "답답", "편안", "지침", "스트레스"],
    "current_focus_project": ["지금", "프로젝트", "집중", "현재 작업"],
}


class UpdateRetriever:
    def classify(self, user_message: str, reply: str) -> dict:
        actions: list[dict] = []
        lowered = user_message.lower()

        if any(token in user_message for token in ["정정", "정확히는", "맞긴 해. 근데", "핵심은", "다만"]):
            actions.append({"type": "new_correction"})

        for state_key, hints in STATE_HINTS.items():
            if any(h in user_message for h in hints):
                actions.append({"type": "state_update", "key": state_key})
                break

        if len(user_message) > 20:
            actions.append({"type": "new_episode"})

        if not actions:
            actions.append({"type": "discard"})

        return {"actions": actions}
