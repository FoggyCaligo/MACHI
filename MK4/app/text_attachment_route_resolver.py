from __future__ import annotations

import json
import re

from config import OLLAMA_DEFAULT_MODEL
from tools.ollama_client import OllamaClient


class TextAttachmentRouteResolver:
    def __init__(self) -> None:
        self.client = OllamaClient(timeout=45, num_predict=64)

    def _excerpt(self, content: str, max_chars: int = 800) -> str:
        compact = re.sub(r"\s+", " ", (content or "")).strip()
        return compact[:max_chars]

    def resolve(self, *, user_request: str, filename: str, content: str, model: str | None = None) -> str:
        system_prompt = (
            "Decide the route for a text attachment request.\n"
            "Return JSON only: {\"route\": \"profile_update\"} or {\"route\": \"general_chat\"}.\n"
            "Choose profile_update only when the user is asking to infer, update, or describe the user's traits, profile, style, preferences, or tendencies from the attached text.\n"
            "Otherwise choose general_chat."
        )
        user_prompt = json.dumps(
            {
                "filename": filename,
                "user_request": (user_request or "")[:600],
                "attachment_excerpt": self._excerpt(content),
            },
            ensure_ascii=False,
        )
        try:
            raw = self.client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model or OLLAMA_DEFAULT_MODEL,
                require_complete=False,
            )
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return "general_chat"
            data = json.loads(match.group(0))
            route = str(data.get("route") or "").strip()
            return route if route in {"profile_update", "general_chat"} else "general_chat"
        except Exception:
            return "general_chat"
