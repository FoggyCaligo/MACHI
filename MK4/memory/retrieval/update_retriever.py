from __future__ import annotations

from memory.constants.language_signals import FIRST_PERSON_MARKERS, PREFERENCE_MARKERS
from memory.services.evidence_normalization_service import EvidenceNormalizationService


STATE_HINTS = {
    "current_mood": ["기분", "우울", "불안", "답답", "편안", "지침", "스트레스"],
    "current_focus_project": ["지금", "프로젝트", "집중", "현재 작업"],
}

CORRECTION_MARKERS = ("정정", "정확히는", "맞긴 해", "핵심은", "다만")
QUESTION_OR_REQUEST_MARKERS = (
    "?",
    "해줘",
    "해줄래",
    "봐줄래",
    "알려줘",
    "가능해",
    "가능할까",
    "부탁",
    "줄래",
)
SELF_MODEL_MARKERS = (
    "나는",
    "내가",
    "저는",
    "제가",
    "편이다",
    "사람이다",
    "성향",
    "습관",
)


class UpdateRetriever:
    """Heuristic fallback extractor for chat memory bundles.

    The primary path should use ChatEvidenceService (model-based structured
    extraction). This class exists only as a resilient fallback when the model
    extractor fails or returns unparsable output.
    """

    def __init__(self) -> None:
        self.normalizer = EvidenceNormalizationService()

    def _normalize(self, text: str) -> str:
        return " ".join((text or "").strip().split())

    def _contains_any(self, text: str, markers: tuple[str, ...] | set[str] | list[str]) -> bool:
        return any(marker for marker in markers if marker and marker in text)

    def _has_first_person(self, lowered: str) -> bool:
        return self._contains_any(lowered, tuple(FIRST_PERSON_MARKERS))

    def _has_preference_or_self_model(self, lowered: str) -> bool:
        return self._contains_any(lowered, tuple(PREFERENCE_MARKERS) + SELF_MODEL_MARKERS)

    def _looks_like_question_or_request(self, cleaned: str) -> bool:
        lowered = cleaned.lower()
        if "?" in cleaned:
            return True
        return self._contains_any(lowered, QUESTION_OR_REQUEST_MARKERS)

    def _infer_source_strength(
        self,
        *,
        cleaned: str,
        lowered: str,
        has_first_person: bool,
        has_state_hint: bool,
        is_question_or_request: bool,
    ) -> str | None:
        if not cleaned or is_question_or_request:
            return None
        if has_first_person and (has_state_hint or self._has_preference_or_self_model(lowered)):
            return "explicit_self_statement"
        if has_first_person or has_state_hint:
            return "repeated_behavior"
        if len(cleaned) >= 30:
            return "temporary_interest"
        return None

    def fallback_bundle(self, user_message: str, reply: str, model: str | None = None) -> dict:
        del reply, model

        cleaned = self._normalize(user_message)
        lowered = cleaned.lower()
        actions: list[dict] = []
        state_payloads: list[dict] = []

        is_question_or_request = self._looks_like_question_or_request(cleaned)
        has_first_person = self._has_first_person(lowered)
        has_state_hint = False

        if self._contains_any(cleaned, CORRECTION_MARKERS):
            actions.append({"type": "new_correction"})

        for state_key, hints in STATE_HINTS.items():
            if any(hint in cleaned for hint in hints):
                actions.append({"type": "state_update", "key": state_key})
                state_payloads.append({"key": state_key, "value": cleaned, "source": "user_explicit"})
                has_state_hint = True
                break

        source_strength = self._infer_source_strength(
            cleaned=cleaned,
            lowered=lowered,
            has_first_person=has_first_person,
            has_state_hint=has_state_hint,
            is_question_or_request=is_question_or_request,
        )
        direct_candidate = source_strength == "explicit_self_statement"

        should_create_episode = bool(cleaned) and len(cleaned) >= 20 and not is_question_or_request
        if should_create_episode:
            actions.append({"type": "new_episode"})

        if not actions:
            actions.append({"type": "discard"})

        parsed = {
            "action_types": [action.get("type") for action in actions if action.get("type")],
            "state_payloads": state_payloads,
            "memory_candidate": {
                "content": cleaned,
                "source_strength": source_strength,
                "direct_candidate": direct_candidate,
                "confidence": 0.8 if direct_candidate else 0.6 if source_strength else 0.0,
            } if cleaned and source_strength and not is_question_or_request else None,
            "correction_candidate": {
                "content": cleaned,
                "reason": "explicit_correction_or_conflict_candidate",
                "confidence": 0.8,
            } if any(action.get("type") == "new_correction" for action in actions) and cleaned else None,
            "episode_candidate": {
                "summary": cleaned[:300],
                "raw_ref": cleaned,
                "importance": 0.8 if direct_candidate else 0.4,
            } if should_create_episode and cleaned else None,
        }
        bundle = self.normalizer.normalize_chat_update_bundle(parsed)
        bundle.update(
            {
                "actions": actions,
                "source_strength": source_strength,
                "direct_candidate": direct_candidate,
                "should_create_episode": should_create_episode,
                "state_payloads": state_payloads,
                "memory_text": cleaned,
                "is_question_or_request": is_question_or_request,
                "extractor": "heuristic_fallback",
            }
        )
        return bundle

    def classify(self, user_message: str, reply: str, model: str | None = None) -> dict:
        return self.fallback_bundle(user_message=user_message, reply=reply, model=model)
