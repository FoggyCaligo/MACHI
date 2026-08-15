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
    final_answer_kind: str = "answer"
    completion_tools: list[str] = field(default_factory=list)


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
        "final_answer_kind": {
            "type": "string",
            "enum": ["answer", "tool_completion", "blocked"],
        },
        "completion_tools": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["final_answer", "tool_calls", "final_answer_kind", "completion_tools"],
    "additionalProperties": False,
}


def _parse_model_turn(raw: str) -> ModelTurn:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        extracted = _extract_braced_json(raw)
        if extracted:
            try:
                data = json.loads(extracted)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Model response must be valid JSON with final_answer and tool_calls: {exc}"
                ) from exc
        else:
            raise RuntimeError("Model response must be JSON with final_answer and tool_calls.")
    if not isinstance(data, dict):
        raise RuntimeError("Model response must be a JSON object.")
    final_answer = data.get("final_answer")
    if final_answer is not None and not isinstance(final_answer, str):
        raise RuntimeError("final_answer must be string or null.")
    tool_calls_raw = data.get("tool_calls")
    if not isinstance(tool_calls_raw, list):
        raise RuntimeError("tool_calls must be a list.")
    final_answer_kind = data.get("final_answer_kind", "answer")
    if final_answer_kind not in {"answer", "tool_completion", "blocked"}:
        raise RuntimeError("final_answer_kind must be answer, tool_completion, or blocked.")
    completion_tools_raw = data.get("completion_tools", [])
    if not isinstance(completion_tools_raw, list) or not all(
        isinstance(item, str) for item in completion_tools_raw
    ):
        raise RuntimeError("completion_tools must be a list of strings.")

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
    return ModelTurn(
        final_answer=final_answer.strip() if isinstance(final_answer, str) else None,
        tool_calls=tool_calls,
        final_answer_kind=final_answer_kind,
        completion_tools=[item.strip() for item in completion_tools_raw if item.strip()],
    )


def _extract_braced_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start:end + 1]


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
                "final_answer_kind": "answer | tool_completion | blocked",
                "completion_tools": ["tool names that support a tool_completion final answer"],
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
            return ModelTurn(final_answer=f"MK5 stub reply.\nmessage={user_message}\nmemory={memory_summary}")
        return ModelTurn(final_answer=f"MK5 stub reply.\nmessage={user_message}")

