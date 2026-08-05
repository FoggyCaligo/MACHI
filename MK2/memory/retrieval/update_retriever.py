from __future__ import annotations

from memory.services.evidence_normalization_service import EvidenceNormalizationService


class UpdateRetriever:
    """Safe no-op fallback for chat extraction failures.

    If model-based chat extraction fails, do not guess meaning with string
    heuristics. Return a discard bundle so failures stay visible.
    """

    def __init__(self) -> None:
        self.normalizer = EvidenceNormalizationService()

    def fallback_bundle(self, user_message: str, reply: str, model: str | None = None) -> dict:
        del user_message, reply, model
        bundle = self.normalizer.normalize_chat_update_bundle(
            {
                "action_types": ["discard"],
                "state_payloads": [],
                "memory_candidate": None,
                "correction_candidate": None,
                "episode_candidate": None,
            }
        )
        bundle.update(
            {
                "extractor": "noop_fallback",
                "fallback_reason": "model_extract_failed",
            }
        )
        return bundle

    def classify(self, user_message: str, reply: str, model: str | None = None) -> dict:
        return self.fallback_bundle(user_message=user_message, reply=reply, model=model)
