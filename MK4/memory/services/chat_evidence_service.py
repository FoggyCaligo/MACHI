from __future__ import annotations

from config import CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH
from memory.retrieval.update_retriever import UpdateRetriever
from memory.services.evidence_extraction_service import EvidenceExtractionService
from memory.services.evidence_normalization_service import EvidenceNormalizationService


class ChatEvidenceService:
    """Model-first chat memory extractor with heuristic fallback."""

    def __init__(self) -> None:
        self.extraction_service = EvidenceExtractionService(timeout=90, num_predict=320, retry_num_predict=224)
        self.normalizer = EvidenceNormalizationService()
        self.fallback_retriever = UpdateRetriever()

    def _build_user_prompt(self, user_message: str, reply: str) -> str:
        cleaned_user = " ".join((user_message or "").strip().split())
        cleaned_reply = " ".join((reply or "").strip().split())
        return (
            "[latest_user_message]\n"
            f"{cleaned_user}\n\n"
            "[assistant_reply]\n"
            f"{cleaned_reply}"
        )

    def extract(self, *, user_message: str, reply: str, model: str | None = None) -> dict:
        user_prompt = self._build_user_prompt(user_message=user_message, reply=reply)
        run = None
        try:
            run = self.extraction_service.run_extract(
                system_prompt_path=CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH,
                user_prompt=user_prompt,
                retry_user_prompt=user_prompt,
                model=model,
                require_complete=True,
            )
        except Exception as exc:  # network / local model failures should fall back safely
            fallback = self.fallback_retriever.fallback_bundle(
                user_message=user_message,
                reply=reply,
                model=model,
            )
            fallback["extractor"] = "heuristic_fallback"
            fallback["extract_error"] = str(exc)
            return fallback

        parsed = self.normalizer.extract_json_object(run.text)
        if not parsed:
            fallback = self.fallback_retriever.fallback_bundle(
                user_message=user_message,
                reply=reply,
                model=model,
            )
            fallback["extractor"] = "heuristic_fallback"
            fallback["extract_error"] = run.error or "parse_failed"
            return fallback

        bundle = self.normalizer.normalize_chat_update_bundle(parsed)
        bundle["extractor"] = "model"
        if run.error:
            bundle["extract_error"] = run.error
        return bundle
