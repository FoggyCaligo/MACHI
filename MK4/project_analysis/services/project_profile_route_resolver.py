from __future__ import annotations

import json
import re

from config import OLLAMA_DEFAULT_MODEL, PROJECT_PROFILE_ROUTE_SYSTEM_PROMPT_PATH, ROUTE_CLASSIFY_NUM_PREDICT
from prompts.prompt_loader import load_prompt_text
from tools.ollama_client import OllamaClient


class ProjectProfileRouteResolver:
    def __init__(self) -> None:
        self.client = OllamaClient(timeout=45, num_predict=ROUTE_CLASSIFY_NUM_PREDICT)

    def resolve(self, *, question: str, model: str | None = None) -> str:
        system_prompt = load_prompt_text(PROJECT_PROFILE_ROUTE_SYSTEM_PROMPT_PATH)
        user_prompt = json.dumps(
            {
                "question": (question or "")[:1200],
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
                return "project_question"
            data = json.loads(match.group(0))
            route = str(data.get("route") or "").strip()
            return route if route in {"profile_question", "project_question"} else "project_question"
        except Exception:
            return "project_question"