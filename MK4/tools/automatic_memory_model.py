from __future__ import annotations

import json
from copy import deepcopy
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
)
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog, missing_required_arguments
from .tool_requirements import get_frozen_tool_requirements, missing_required_tools
from .tool_runtime import ToolCall, ToolDefinition


_MODEL_TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": ["string", "null"]},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["tool", "arguments"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["message", "tool_calls"],
    "additionalProperties": False,
}


class AutomaticMemoryContextOllamaToolChatModel(OllamaToolChatModel):
    """Expose automatic memory, frozen tool obligations, and a small action contract."""

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
        frozen = get_frozen_tool_requirements()
        required_tools = list(frozen.required_tools) if frozen is not None else []
        missing_tools = list(missing_required_tools(frozen, tool_history)) if frozen is not None else []
        user_payload = {
            "user_message": user_message,
            "authorization_context": get_authorization_context(),
            "frozen_tool_requirements": {
                "required_tools": required_tools,
                "missing_tools": missing_tools,
                "contract": (
                    "Every tool in missing_tools still needs a successful explicit execution before final answer release. "
                    "Automatic memory is context only and does not satisfy an explicit tool requirement. "
                    "Tools outside required_tools remain available for optional exploration."
                ),
            },
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
                response_format=_model_turn_schema_for_tools(tool_names),
            )
        except ValueError as exc:
            raise ModelRequestError(str(exc)) from exc
        try:
            turn = _parse_lightweight_turn(raw)
        except ModelOutputParseError as exc:
            _log_model_output_failure(raw=raw, error=exc)
            raise
        return _manual_for_incomplete_tool_calls(
            turn,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )


def _model_turn_schema_for_tools(tool_names: list[str]) -> dict[str, Any]:
    schema = deepcopy(_MODEL_TURN_SCHEMA)
    if tool_names:
        tool_schema = schema["properties"]["tool_calls"]["items"]["properties"]["tool"]
        tool_schema["enum"] = sorted(set(tool_names))
    return schema


def _parse_lightweight_turn(raw: str) -> ModelTurn:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelOutputParseError(f"Model response must be valid JSON with message and tool_calls: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelOutputParseError("Model response must be a JSON object.")

    message = data.get("message")
    if message is not None and not isinstance(message, str):
        raise ModelOutputParseError("message must be string or null.")
    tool_calls_raw = data.get("tool_calls")
    if not isinstance(tool_calls_raw, list):
        raise ModelOutputParseError("tool_calls must be a list.")

    tool_calls: list[ToolCall] = []
    for idx, item in enumerate(tool_calls_raw):
        if not isinstance(item, dict):
            raise ModelOutputParseError(f"tool_calls[{idx}] must be an object.")
        tool = item.get("tool")
        arguments = item.get("arguments")
        if not isinstance(tool, str) or not tool.strip():
            raise ModelOutputParseError(f"tool_calls[{idx}].tool must be a non-empty string.")
        if not isinstance(arguments, dict):
            raise ModelOutputParseError(f"tool_calls[{idx}].arguments must be an object.")
        tool_calls.append(ToolCall(tool=tool.strip(), arguments=arguments))

    cleaned_message = message.strip() if isinstance(message, str) else None
    return ModelTurn(final_answer=cleaned_message or None, tool_calls=tool_calls)


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
    )
