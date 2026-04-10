from __future__ import annotations

import json
import re
from typing import Any

from config import CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH, OLLAMA_DEFAULT_MODEL
from prompts.prompt_loader import load_prompt_text
from tools.ollama_client import OllamaClient


ALLOWED_ACTION_TYPES = {
    "discard",
    "profile_candidate",
    "state_update",
    "new_correction",
    "new_episode",
}
ALLOWED_SOURCE_STRENGTHS = {
    "temporary_interest",
    "repeated_behavior",
    "explicit_self_statement",
}


class UpdateRetriever:
    def __init__(self) -> None:
        self.client = OllamaClient(timeout=45, num_predict=256)
        self.system_prompt = load_prompt_text(CHAT_UPDATE_EXTRACT_SYSTEM_PROMPT_PATH)

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {}

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    def _normalize_actions(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return ["discard"]

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            action = str(item or "").strip()
            if action not in ALLOWED_ACTION_TYPES:
                continue
            if action in seen:
                continue
            seen.add(action)
            normalized.append(action)

        return normalized or ["discard"]

    @staticmethod
    def _bounded_score(value: Any, default: float = 0.0) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return default
        return min(max(score, 0.0), 1.0)

    def _normalize_state_payloads(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            payload_value = str(item.get("value") or "").strip()
            if not key or not payload_value:
                continue
            normalized.append(
                {
                    "key": key,
                    "value": payload_value,
                    "source": "user_explicit",
                    "confidence": self._bounded_score(item.get("confidence"), default=0.6),
                }
            )
        return normalized

    def _normalize_memory_candidate(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        content = str(value.get("content") or "").strip()
        if not content:
            return None

        source_strength = str(value.get("source_strength") or "").strip()
        if source_strength not in ALLOWED_SOURCE_STRENGTHS:
            source_strength = ""

        return {
            "content": content,
            "source_strength": source_strength,
            "direct_candidate": bool(value.get("direct_candidate")),
            "confidence": self._bounded_score(value.get("confidence"), default=0.0),
        }

    def _normalize_correction_candidate(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        content = str(value.get("content") or "").strip()
        if not content:
            return None

        reason = str(value.get("reason") or "user_explicit_correction").strip() or "user_explicit_correction"
        return {
            "content": content,
            "reason": reason,
            "confidence": self._bounded_score(value.get("confidence"), default=0.7),
        }

    def _normalize_episode_candidate(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        summary = str(value.get("summary") or "").strip()
        if not summary:
            return None

        raw_ref = str(value.get("raw_ref") or "").strip() or summary
        return {
            "summary": summary,
            "raw_ref": raw_ref,
            "importance": self._bounded_score(value.get("importance"), default=0.5),
        }

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

        parsed = self._extract_json_object(raw)
        action_types = self._normalize_actions(parsed.get("action_types"))
        state_payloads = self._normalize_state_payloads(parsed.get("state_payloads"))
        memory_candidate = self._normalize_memory_candidate(parsed.get("memory_candidate"))
        correction_candidate = self._normalize_correction_candidate(parsed.get("correction_candidate"))
        episode_candidate = self._normalize_episode_candidate(parsed.get("episode_candidate"))

        if memory_candidate and "profile_candidate" not in action_types:
            action_types.append("profile_candidate")
        if correction_candidate and "new_correction" not in action_types:
            action_types.append("new_correction")
        if episode_candidate and "new_episode" not in action_types:
            action_types.append("new_episode")
        if state_payloads and "state_update" not in action_types:
            action_types.append("state_update")

        meaningful = [a for a in action_types if a != "discard"]
        if meaningful:
            action_types = meaningful
        else:
            action_types = ["discard"]

        return {
            "action_types": action_types,
            "state_payloads": state_payloads,
            "memory_candidate": memory_candidate,
            "correction_candidate": correction_candidate,
            "episode_candidate": episode_candidate,
        }
