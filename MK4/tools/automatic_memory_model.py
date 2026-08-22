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
    _response_schema_for_tools,
)
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog, missing_required_arguments
from .tool_runtime import ToolCall, ToolDefinition


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
        tool_names = [tool.name for tool in tool_definitions]
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
            "tool_history": [_compact_tool_history_event(event) for event in tool_history],
        }
        try:
            raw = await ollama_chat(
                system=system,
                user=json.dumps(user_payload, ensure_ascii=False),
                model=model,
                response_format=_response_schema_for_tools(tool_names),
            )
        except ValueError as exc:
            raise ModelRequestError(str(exc)) from exc
        try:
            turn = _parse_model_turn(raw)
        except ModelOutputParseError as exc:
            _log_model_output_failure(raw=raw, error=exc)
            raise
        return _manual_for_incomplete_tool_calls(
            turn,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )


def _manual_for_incomplete_tool_calls(
    turn: ModelTurn,
    *,
    tool_definitions: list[ToolDefinition],
    tool_history: list[dict[str, Any]],
) -> ModelTurn:
    """Keep valid calls direct; consult tool_manual only when required inputs are missing."""
    definitions = {definition.name: definition for definition in tool_definitions}
    if "tool_manual" not in definitions or not turn.tool_calls:
        return turn

    consulted = {
        str(event.get("result", {}).get("tool") or "")
        for event in tool_history
        if event.get("tool") == "tool_manual"
        and isinstance(event.get("result"), dict)
        and event["result"].get("ok") is True
    }
    manual_names: list[str] = []
    executable_calls: list[ToolCall] = []

    for call in turn.tool_calls:
        if call.tool == "tool_manual" or call.tool in consulted:
            executable_calls.append(call)
            continue
        definition = definitions.get(call.tool)
        if definition is None:
            executable_calls.append(call)
            continue
        if not missing_required_arguments(call.arguments, definition):
            executable_calls.append(call)
            continue
        if call.tool not in manual_names:
            manual_names.append(call.tool)

    if not manual_names:
        return turn

    return ModelTurn(
        tool_calls=[
            *(ToolCall(tool="tool_manual", arguments={"tool": name}) for name in manual_names),
            *executable_calls,
        ],
        final_answer_kind="answer",
    )
