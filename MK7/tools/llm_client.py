from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from .ollama_client import chat as ollama_chat
from .tool_runtime import ToolCall, ToolDefinition


@dataclass(slots=True)
class ModelTurn:
    final_answer: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[str],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn: ...


_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "final_answer": {"type": ["string", "null"]},
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
    "required": ["final_answer", "tool_calls"],
    "additionalProperties": False,
}


def _parse_model_turn(raw: str) -> ModelTurn:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Model response must be a JSON object.")
    final_answer = data.get("final_answer")
    if final_answer is not None and not isinstance(final_answer, str):
        raise RuntimeError("final_answer must be string or null.")
    tool_calls_raw = data.get("tool_calls")
    if not isinstance(tool_calls_raw, list):
        raise RuntimeError("tool_calls must be a list.")

    tool_calls: list[ToolCall] = []
    for idx, item in enumerate(tool_calls_raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"tool_calls[{idx}] must be an object.")
        tool = item.get("tool")
        arguments = item.get("arguments")
        if not isinstance(tool, str) or not tool.strip():
            raise RuntimeError(f"tool_calls[{idx}].tool must be a non-empty string.")
        if not isinstance(arguments, dict):
            raise RuntimeError(f"tool_calls[{idx}].arguments must be an object.")
        tool_calls.append(ToolCall(tool=tool.strip(), arguments=arguments))
    return ModelTurn(final_answer=final_answer.strip() if isinstance(final_answer, str) else None, tool_calls=tool_calls)


class OllamaToolChatModel:
    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[str],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        tool_spec_payload = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tool_definitions
        ]
        user_payload = {
            "user_message": user_message,
            "memory_summary": memory_summary,
            "tools": tool_spec_payload,
            "tool_history": tool_history,
            "output_contract": {
                "final_answer": "string or null",
                "tool_calls": [{"tool": "tool name", "arguments": {"...": "..."}}],
            },
        }
        raw = await ollama_chat(
            system=system,
            user=json.dumps(user_payload, ensure_ascii=False),
            model=model,
            response_format=_RESPONSE_SCHEMA,
        )
        return _parse_model_turn(raw)


class StubChatModel:
    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[str],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        if not tool_history and "search" in user_message.lower():
            return ModelTurn(
                tool_calls=[ToolCall(tool="internet_search", arguments={"query": user_message})]
            )
        if memory_summary:
            return ModelTurn(final_answer=f"MK7 stub reply.\nmessage={user_message}\nmemory={memory_summary}")
        return ModelTurn(final_answer=f"MK7 stub reply.\nmessage={user_message}")
