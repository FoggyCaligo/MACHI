from __future__ import annotations

import json
from typing import Any

from .llm_client import (
    ModelOutputParseError,
    ModelRequestError,
    ModelTurn,
    _compact_memory_item,
    _compact_tool_history_event,
)
from .ollama_client import chat as ollama_chat
from .tool_runtime import ToolCall, ToolDefinition


class RequiredToolChatModel:
    """Call Ollama with a response schema that permits exactly one required tool call."""

    async def next_required_tool(
        self,
        *,
        required_tool: str,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        definition = next(
            (item for item in tool_definitions if item.name == required_tool),
            None,
        )
        if definition is None:
            raise ModelRequestError(f"Required tool is not model-visible: {required_tool}")

        user_payload = {
            "user_message": user_message,
            "memory_summary": [_compact_memory_item(item) for item in memory_summary],
            "tools": [required_tool],
            "tool_history": [_compact_tool_history_event(event) for event in tool_history],
        }
        try:
            raw = await ollama_chat(
                system=system,
                user=json.dumps(user_payload, ensure_ascii=False),
                model=model,
                response_format=_required_tool_response_schema(definition),
            )
        except ValueError as exc:
            raise ModelRequestError(str(exc)) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelOutputParseError(
                f"Required-tool response must be valid JSON: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ModelOutputParseError("Required-tool response must be a JSON object.")
        if data.get("final_answer") is not None:
            raise ModelOutputParseError("Required-tool response cannot contain final_answer.")
        calls = data.get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1:
            raise ModelOutputParseError("Required-tool response must contain exactly one tool call.")
        call = calls[0]
        if not isinstance(call, dict):
            raise ModelOutputParseError("Required-tool call must be an object.")
        tool_name = call.get("tool")
        arguments = call.get("arguments")
        if tool_name != required_tool:
            raise ModelOutputParseError(
                f"Required-tool response must call {required_tool}, got {tool_name!r}."
            )
        if not isinstance(arguments, dict):
            raise ModelOutputParseError("Required-tool arguments must be an object.")

        return ModelTurn(
            tool_calls=[ToolCall(tool=required_tool, arguments=arguments)],
            final_answer_kind="answer",
        )


def _required_tool_response_schema(definition: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "final_answer": {"type": "null"},
            "tool_calls": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "enum": [definition.name]},
                        "arguments": definition.input_schema,
                    },
                    "required": ["tool", "arguments"],
                    "additionalProperties": False,
                },
            },
            "final_answer_kind": {
                "type": "string",
                "enum": ["answer"],
            },
            "completion_tools": {
                "type": "array",
                "maxItems": 0,
                "items": {"type": "string"},
            },
        },
        "required": ["final_answer", "tool_calls", "final_answer_kind", "completion_tools"],
        "additionalProperties": False,
    }
