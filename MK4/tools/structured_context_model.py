from __future__ import annotations

import json
from typing import Any

from .account_authorization import get_authorization_context
from .llm_client import (
    ModelOutputParseError,
    ModelRequestError,
    ModelTurn,
    OllamaToolChatModel,
    _compact_tool_history_event,
    _log_model_output_failure,
    _parse_model_turn,
)
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog
from .tool_runtime import ToolCall, ToolDefinition


class StructuredContextOllamaToolChatModel(OllamaToolChatModel):
    """Expose only request-scoped authorization, tool catalog, and tool history."""

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
        _ = memory_summary
        tool_names = [tool.name for tool in tool_definitions]
        user_payload = {
            "user_message": user_message,
            "authorization_context": get_authorization_context(),
            "tool_catalog": compact_tool_catalog(tool_definitions),
            "tool_history": [_compact_tool_history_event(event) for event in tool_history],
        }
        try:
            raw = await ollama_chat(
                system=system,
                user=json.dumps(user_payload, ensure_ascii=False),
                model=model,
                response_format=_agent_action_schema(tool_names),
            )
        except ValueError as exc:
            raise ModelRequestError(str(exc)) from exc
        try:
            turn = _parse_agent_action(raw, tool_names=tool_names)
            turn = _defer_unconsulted_tool_manual(
                turn,
                tool_definitions=tool_definitions,
                tool_history=tool_history,
            )
            _validate_single_agent_action(turn)
        except ModelOutputParseError as exc:
            _log_model_output_failure(raw=raw, error=exc)
            raise
        return turn


def _agent_action_schema(tool_names: list[str]) -> dict[str, Any]:
    names = sorted(set(tool_names))
    name_set = set(names)
    if name_set == {"recall_memory"}:
        actions = ["tool"]
    elif {"write_memory", "revise_memory"} & name_set:
        actions = ["tool", "done"] if "finish_memory_commit" in name_set else ["tool"]
    elif names:
        actions = ["tool", "answer"]
    else:
        actions = ["answer"]

    tool_property: dict[str, Any] = {"type": "string"}
    if names:
        tool_property["enum"] = names
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": actions},
            "tool": tool_property,
            "arguments": {"type": "object"},
            "content": {"type": "string"},
            "kind": {"type": "string", "enum": ["answer", "tool_completion", "blocked"]},
            "completion_tools": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action"],
        "additionalProperties": False,
    }


def _parse_agent_action(raw: str, *, tool_names: list[str]) -> ModelTurn:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _parse_model_turn(raw)
    if not isinstance(data, dict) or "action" not in data:
        return _parse_model_turn(raw)

    action = data.get("action")
    if action == "tool":
        tool = data.get("tool")
        arguments = data.get("arguments", {})
        if not isinstance(tool, str) or not tool.strip():
            raise ModelOutputParseError("tool action requires a non-empty tool name")
        if tool_names and tool not in tool_names:
            raise ModelOutputParseError(f"tool action requested unexposed tool: {tool}")
        if not isinstance(arguments, dict):
            raise ModelOutputParseError("tool action arguments must be an object")
        return ModelTurn(tool_calls=[ToolCall(tool=tool.strip(), arguments=arguments)])

    if action == "answer":
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelOutputParseError("answer action requires non-empty content")
        kind = data.get("kind", "answer")
        if kind not in {"answer", "tool_completion", "blocked"}:
            raise ModelOutputParseError("answer kind is invalid")
        completion_tools = data.get("completion_tools", [])
        if not isinstance(completion_tools, list) or not all(isinstance(item, str) for item in completion_tools):
            raise ModelOutputParseError("completion_tools must be a list of strings")
        return ModelTurn(
            final_answer=content.strip(),
            final_answer_kind=kind,
            completion_tools=[item.strip() for item in completion_tools if item.strip()],
        )

    if action == "done":
        if "finish_memory_commit" not in tool_names:
            raise ModelOutputParseError("done action is only valid after a successful memory mutation")
        return ModelTurn(tool_calls=[ToolCall(tool="finish_memory_commit", arguments={})])

    raise ModelOutputParseError(f"unknown agent action: {action!r}")


def _defer_unconsulted_tool_manual(
    turn: ModelTurn,
    *,
    tool_definitions: list[ToolDefinition],
    tool_history: list[dict[str, Any]],
) -> ModelTurn:
    if len(turn.tool_calls) != 1:
        return turn
    definitions = {definition.name for definition in tool_definitions}
    if "tool_manual" not in definitions:
        return turn
    call = turn.tool_calls[0]
    if call.tool == "tool_manual":
        return turn
    consulted = {
        str(event.get("result", {}).get("tool") or "")
        for event in tool_history
        if event.get("tool") == "tool_manual"
        and isinstance(event.get("result"), dict)
        and event["result"].get("ok") is True
    }
    if call.tool in consulted:
        return turn
    return ModelTurn(tool_calls=[ToolCall(tool="tool_manual", arguments={"tool": call.tool})])


def _validate_single_agent_action(turn: ModelTurn) -> None:
    if len(turn.tool_calls) > 1:
        raise ModelOutputParseError("compact agent protocol permits at most one tool call per model round")
    if turn.final_answer is not None and turn.tool_calls:
        raise ModelOutputParseError("compact agent protocol cannot answer and call a tool in the same model round")
