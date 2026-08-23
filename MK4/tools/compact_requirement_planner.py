from __future__ import annotations

import json
from typing import Any

from .llm_client import ModelRequestError
from .ollama_client import chat as ollama_chat
from .tool_catalog import requirement_tool_catalog
from .tool_requirements import (
    FrozenToolRequirements,
    ToolRequirementPlanError,
    _parse_requirement_plan,
)
from .tool_runtime import ToolDefinition


_COMPACT_REQUIREMENT_INSTRUCTION = """
Evaluate every exposed tool independently for the single current user input.

The payload also contains up to four immediately preceding user/assistant dialogue pairs. Use those pairs only to resolve omitted subjects, references, constraints, and continuation context in the current input. They are conversational context, not evidence, and they never count as a successful tool execution for the current request.

For each tool, inspect only the kind of information or action result that a successful execution provides. Ask one question: after interpreting the current input with the recent dialogue context, is a new successful result of this kind required to answer the current input correctly?

Return true when that exact tool's result kind is required. Return false when the result kind is unnecessary, merely useful, optional, or only capable of improving an answer that can already be correct without it.

Do not compare tools with one another, choose substitutes, build OR groups, draft an answer, construct tool arguments, or use tool names as semantic shortcuts. All true tools are independently required and must later succeed before release.

Judge the current request as written and resolved by the recent dialogue. Do not add unstated user constraints. A concrete real-world recommendation can require external factual evidence when correctness depends on facts about actual current options; a timeless conceptual explanation does not require external evidence merely because research could improve it.

Return only the required structured booleans.
""".strip()


async def plan_compact_tool_requirements(
    *,
    user_message: str,
    recent_dialogue_pairs: list[dict[str, str]],
    model: str | None,
    tool_definitions: list[ToolDefinition],
) -> FrozenToolRequirements:
    if not tool_definitions:
        return FrozenToolRequirements()

    tool_names = sorted({definition.name for definition in tool_definitions})
    response_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "tool_requirements": {
                "type": "object",
                "properties": {name: {"type": "boolean"} for name in tool_names},
                "required": tool_names,
                "additionalProperties": False,
            },
        },
        "required": ["tool_requirements"],
        "additionalProperties": False,
    }
    payload = {
        "recent_dialogue_pairs": recent_dialogue_pairs[-4:],
        "user_input": user_message,
        "tools": requirement_tool_catalog(tool_definitions),
    }
    try:
        raw = await ollama_chat(
            system=_COMPACT_REQUIREMENT_INSTRUCTION,
            user=json.dumps(payload, ensure_ascii=False),
            model=model,
            response_format=response_schema,
        )
    except ValueError as exc:
        raise ModelRequestError(str(exc)) from exc

    try:
        data = json.loads(raw)
        return _parse_requirement_plan(data, tool_names=tool_names)
    except json.JSONDecodeError as exc:
        raise ToolRequirementPlanError(
            f"Tool requirement plan must be valid JSON: {exc}"
        ) from exc
