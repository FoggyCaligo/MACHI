from __future__ import annotations

import json
from typing import Any

from .account_authorization import get_authorization_context
from .llm_client import (
    ModelOutputParseError,
    ModelRequestError,
    ModelTurn,
    OllamaToolChatModel,
    _compact_memory_item,
    _compact_tool_history_event,
    _log_model_output_failure,
    _parse_model_turn,
    _require_tool_manuals,
    _response_schema_for_tools,
)
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog
from .tool_runtime import ToolDefinition


class AutomaticMemoryContextOllamaToolChatModel(OllamaToolChatModel):
    """Expose automatic graph activation and authorization as explicit model context."""

    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        user_payload = {
            "user_message": user_message,
            "authorization_context": get_authorization_context(),
            "automatic_memory_context": {
                "source": "automatic_graph_activation",
                "scope": "partial",
                "is_tool_result": False,
                "items": [_compact_memory_item(item) for item in memory_summary],
            },
            "tool_catalog": compact_tool_catalog(tool_definitions),
            "tools": [tool.name for tool in tool_definitions],
            "tool_history": [_compact_tool_history_event(event) for event in tool_history],
        }
        try:
            raw = await ollama_chat(
                system=system,
                user=json.dumps(user_payload, ensure_ascii=False),
                model=model,
                response_format=_response_schema_for_tools([tool.name for tool in tool_definitions]),
            )
        except ValueError as exc:
            raise ModelRequestError(str(exc)) from exc
        try:
            turn = _parse_model_turn(raw)
        except ModelOutputParseError as exc:
            _log_model_output_failure(raw=raw, error=exc)
            raise
        return _require_tool_manuals(
            turn,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )
