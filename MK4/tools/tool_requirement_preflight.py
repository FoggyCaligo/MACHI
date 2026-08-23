from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from .llm_client import ModelRequestError
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog
from .tool_requirements import (
    FrozenToolRequirements,
    ToolRequirementPlanError,
    _ACTIVE_REQUIREMENTS,
    _debug_requirement_plan,
    _debug_requirement_plan_error,
    _parse_requirement_plan,
)
from .tool_runtime import ToolDefinition


_PRE_MEMORY_TOOL_REQUIREMENT_INSTRUCTION = """
Decide which currently exposed tools must actually be executed to honestly complete the user's request.

This decision happens before automatic memory recall. You do not have automatic memory results yet, and you must not assume that later automatic recall will satisfy a tool requirement.
Do not draft the answer and do not invent capabilities.

Process:
1. Judge the user's request itself, the current date, and the exposed tool catalog only.
2. The response schema contains one boolean property for every exposed tool. Judge every property independently as true or false.
3. Set a tool to true when executing that tool is part of a minimal valid way to obtain information or perform an action required by the request.
4. A tool that is merely related, potentially useful, or nice to have is false.
5. Persistent-memory recall is for retrieving the user's past conversation, preferences, decisions, recommendations, and project context. If the request requires such past information, recall may be true even though automatic memory will be supplied later.
6. Automatic memory supplied later is framework context, not a successful execution of recall_memory. A frozen recall requirement is satisfied only by a successful explicit recall_memory tool event.
7. Public or external facts whose truth can reasonably differ today from yesterday require an appropriate current external tool. Persistent memory is not a refresh mechanism for those facts.
8. Stable conceptual explanations that do not require retrieval or action remain tool-free.
9. After judging all booleans, group only true tools by substitutability in required_groups:
   - tools in the same group are alternatives; one successful tool in that group is enough for that part of the request,
   - tools that are jointly necessary must be in different groups,
   - a true tool with no substitute forms a one-tool group.
10. Never place a false tool in a group. Every true tool must appear in exactly one group.
11. Use only tool names present in the response schema/tool catalog.

The final required_groups represent AND across groups and OR within each group.
""".strip()


async def plan_and_freeze_before_memory(
    *,
    user_message: str,
    model: str | None,
    tool_definitions: list[ToolDefinition],
    current_date: str | None = None,
) -> FrozenToolRequirements:
    """Plan required tool execution before automatic memory recall and freeze it for the request."""
    if not tool_definitions:
        requirements = FrozenToolRequirements()
        _ACTIVE_REQUIREMENTS.set(requirements)
        _debug_requirement_plan(requirements)
        return requirements

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
            "required_groups": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "string", "enum": tool_names},
                    "minItems": 1,
                    "uniqueItems": True,
                },
            },
        },
        "required": ["tool_requirements", "required_groups"],
        "additionalProperties": False,
    }
    payload = {
        "user_request": user_message,
        "current_date": current_date or datetime.now().astimezone().date().isoformat(),
        "automatic_memory_status": "not_recalled_yet",
        "tool_catalog": compact_tool_catalog(tool_definitions),
    }
    try:
        raw = await ollama_chat(
            system=_PRE_MEMORY_TOOL_REQUIREMENT_INSTRUCTION,
            user=json.dumps(payload, ensure_ascii=False),
            model=model,
            response_format=response_schema,
        )
    except ValueError as exc:
        raise ModelRequestError(str(exc)) from exc

    try:
        data = json.loads(raw)
        requirements = _parse_requirement_plan(data, tool_names=tool_names)
    except (json.JSONDecodeError, ToolRequirementPlanError) as exc:
        error = (
            ToolRequirementPlanError(f"Tool requirement plan must be valid JSON: {exc}")
            if isinstance(exc, json.JSONDecodeError)
            else exc
        )
        _debug_requirement_plan_error(raw=raw, error=error)
        raise error

    _ACTIVE_REQUIREMENTS.set(requirements)
    _debug_requirement_plan(requirements)
    return requirements


def model_facing_definitions(tool_definitions: list[ToolDefinition]) -> list[ToolDefinition]:
    """Apply the same structural model-facing names used by ModelToolNameAdapter."""
    converted: list[ToolDefinition] = []
    seen_names: set[str] = set()
    for definition in tool_definitions:
        schema = dict(definition.input_schema) if isinstance(definition.input_schema, dict) else {}
        model_name_raw = schema.pop("x-model-name", None)
        model_name = str(model_name_raw).strip() if model_name_raw is not None else definition.name
        if not model_name:
            raise ValueError(f"x-model-name must be a non-empty string for {definition.name}")
        if model_name in seen_names:
            raise ValueError(f"Duplicate model-facing tool name: {model_name}")
        seen_names.add(model_name)
        converted.append(
            ToolDefinition(
                name=model_name,
                description=definition.description,
                input_schema=schema,
                model_visible=definition.model_visible,
            )
        )
    return converted
