from __future__ import annotations

from memory.services.evidence_normalization_service import EvidenceNormalizationService


class UpdateRetriever:
    """Fallback extractor that preserves failure visibility without heuristics.

    This fallback intentionally does not perform keyword matching, string rules,
    or implicit language interpretation. When the model extractor fails, the
    system should surface the failure clearly instead of silently fabricating a
    memory update from hardcoded rules.
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
        bundle.update(
            {
                "actions": [{"type": "discard"}],
                "extractor": "no_op_fallback",
                "extract_error": "chat_extractor_failed",
            }
        )
        return bundle

    def classify(self, user_message: str, reply: str, model: str | None = None) -> dict:
        return self.fallback_bundle(user_message=user_message, reply=reply, model=model)
