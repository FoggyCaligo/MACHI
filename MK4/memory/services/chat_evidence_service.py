from __future__ import annotations

import time

from config import CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH
from memory.retrieval.update_retriever import UpdateRetriever
from memory.services.evidence_extraction_service import EvidenceExtractionService
from memory.services.evidence_normalization_service import EvidenceNormalizationService


def _log(message: str) -> None:
    print(f"[MEMORY] {message}", flush=True)


class ChatEvidenceService:
    """Model-first chat memory extractor with safe no-op fallback."""

    def __init__(self) -> None:
        self.extraction_service = EvidenceExtractionService(timeout=90, num_predict=320, retry_num_predict=224)
        self.normalizer = EvidenceNormalizationService()
        self.fallback_retriever = UpdateRetriever()

    def _build_user_prompt(self, user_message: str) -> str:
        cleaned_user = " ".join((user_message or "").strip().split())
        return "[latest_user_message]\n" + cleaned_user

    def extract(self, *, user_message: str, reply: str, model: str | None = None) -> dict:
        started_at = time.perf_counter()
        reply_for_fallback = reply
        user_prompt = self._build_user_prompt(user_message=user_message)

        try:
            model_started_at = time.perf_counter()
            run = self.extraction_service.run_extract(
                system_prompt_path=CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH,
                user_prompt=user_prompt,
                retry_user_prompt=user_prompt,
                model=model,
                require_complete=True,
            )
            model_elapsed = time.perf_counter() - model_started_at
        except Exception as exc:  # network / local model failures should fall back safely
            fallback_started_at = time.perf_counter()
            fallback = self.fallback_retriever.fallback_bundle(
                user_message=user_message,
                reply=reply_for_fallback,
                model=model,
            )
            fallback_elapsed = time.perf_counter() - fallback_started_at
            fallback["extractor"] = "noop_fallback"
            fallback["extract_error"] = str(exc)
            total_elapsed = time.perf_counter() - started_at
            _log(
                "chat_evidence fallback | "
                f"reason=exception | fallback_elapsed={fallback_elapsed:.2f}s | total={total_elapsed:.2f}s"
            )
            return fallback

        parse_started_at = time.perf_counter()
        parsed = self.normalizer.extract_json_object(run.text)
        parse_elapsed = time.perf_counter() - parse_started_at
        if not parsed:
            fallback_started_at = time.perf_counter()
            fallback = self.fallback_retriever.fallback_bundle(
                user_message=user_message,
                reply=reply_for_fallback,
                model=model,
            )
            fallback_elapsed = time.perf_counter() - fallback_started_at
            fallback["extractor"] = "noop_fallback"
            fallback["extract_error"] = run.error or "parse_failed"
            total_elapsed = time.perf_counter() - started_at
            _log(
                "chat_evidence fallback | "
                f"reason=parse_failed | model_elapsed={model_elapsed:.2f}s | parse_elapsed={parse_elapsed:.2f}s | "
                f"fallback_elapsed={fallback_elapsed:.2f}s | total={total_elapsed:.2f}s"
            )
            return fallback

        normalize_started_at = time.perf_counter()
        bundle = self.normalizer.normalize_chat_update_bundle(parsed)
        normalize_elapsed = time.perf_counter() - normalize_started_at
        bundle["extractor"] = "model"
        if run.error:
            bundle["extract_error"] = run.error

        total_elapsed = time.perf_counter() - started_at
        evidence_count = len(bundle.get("evidence_envelopes") or [])
        action_count = len(bundle.get("action_types") or [])
        _log(
            "chat_evidence extract | "
            f"model_elapsed={model_elapsed:.2f}s | parse_elapsed={parse_elapsed:.2f}s | "
            f"normalize_elapsed={normalize_elapsed:.2f}s | envelopes={evidence_count} | "
            f"actions={action_count} | total={total_elapsed:.2f}s"
        )
        return bundle
