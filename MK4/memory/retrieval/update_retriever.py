from __future__ import annotations

import json

from config import CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH, OLLAMA_DEFAULT_MODEL
from memory.services.evidence_normalization_service import EvidenceNormalizationService
from prompts.prompt_loader import load_prompt_text
from tools.ollama_client import OllamaClient


class UpdateRetriever:
    def __init__(self) -> None:
        self.client = OllamaClient(timeout=45, num_predict=256)
        self.system_prompt = load_prompt_text(CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH)
        self.normalizer = EvidenceNormalizationService()

    def classify(self, user_message: str, reply: str, model: str | None = None) -> dict:
        user_payload = json.dumps(
            {
                "user_message": str(user_message or "")[:2000],
                "assistant_reply": str(reply or "")[:2000],
            },
            ensure_ascii=False,
        )

        try:
            raw = self.client.chat(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                model=model or OLLAMA_DEFAULT_MODEL,
                require_complete=True,
                truncated_notice=None,
            )
        except Exception:
            return {
                "action_types": ["discard"],
                "state_payloads": [],
                "memory_candidate": None,
                "correction_candidate": None,
                "episode_candidate": None,
            }

        parsed = self.normalizer.extract_json_object(raw)
        return self.normalizer.normalize_chat_update(parsed)
