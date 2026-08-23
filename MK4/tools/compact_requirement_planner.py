from __future__ import annotations

from datetime import datetime
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
Decide which exposed tools must actually succeed before the user's request can be answered honestly.
Return one boolean for every exposed tool. true means that exact tool is mandatory; false means it is only optional or irrelevant. All true tools are independently required; there is no substitution group.

Judge only the user request, current date, and tool summaries. Do not draft the answer or tool arguments.
Use explicit persistent-memory recall only when the request requires the user's past conversation, preferences, decisions, recommendations, or project context. Automatic memory supplied later does not satisfy an explicit recall requirement.
Information whose value or state could reasonably differ today from yesterday requires an appropriate current external tool. Stable conceptual explanations can remain tool-free.
Do not invent capabilities or mark a tool true merely because it could be useful.
""".strip()


async def plan_compact_tool_requirements(
    *,
    user_message: str,
    model: str | None,
    tool_definitions: list[ToolDefinition],
    current_date: str | None = None,
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
        "user_request": user_message,
        "current_date": current_date or datetime.now().astimezone().date().isoformat(),
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
