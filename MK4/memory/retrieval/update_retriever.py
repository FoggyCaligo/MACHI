from __future__ import annotations

from memory.services.evidence_normalization_service import EvidenceNormalizationService


class UpdateRetriever:
    """Minimal non-semantic fallback for chat memory bundles.

    This class intentionally does not interpret raw language with hardcoded
    keyword lists or regex rules. When the model-based extractor fails, we fall
    back to a safe no-op bundle instead of inventing memory updates through
    heuristic guesses.
    """

    def __init__(self) -> None:
        self.normalizer = EvidenceNormalizationService()

    def fallback_bundle(self, user_message: str, reply: str, model: str | None = None) -> dict:
        del user_message, reply, model
        parsed = {
            "action_types": ["discard"],
            "state_payloads": [],
            "memory_candidate": None,
            "correction_candidate": None,
            "episode_candidate": None,
        }
        bundle = self.normalizer.normalize_chat_update_bundle(parsed)
        bundle["fallback_mode"] = "safe_noop"
        return bundle

    def classify(self, user_message: str, reply: str, model: str | None = None) -> dict:
        return self.fallback_bundle(user_message=user_message, reply=reply, model=model)
