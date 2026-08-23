from __future__ import annotations

from copy import deepcopy

from .tool_requirements import (
    FrozenToolRequirements,
    freeze_tool_requirements,
    plan_tool_requirements,
    _debug_requirement_plan,
)
from .tool_runtime import ToolDefinition


async def plan_and_freeze_before_memory(
    *,
    user_message: str,
    model: str | None,
    tool_definitions: list[ToolDefinition],
    current_date: str | None = None,
) -> FrozenToolRequirements:
    """Plan exact required tool executions before automatic recall, then freeze them."""
    model_definitions = model_facing_definitions(tool_definitions)
    requirements = await plan_tool_requirements(
        user_message=user_message,
        model=model,
        tool_definitions=model_definitions,
        current_date=current_date,
    )
    freeze_tool_requirements(requirements)
    _debug_requirement_plan(requirements)
    return requirements


def model_facing_definitions(tool_definitions: list[ToolDefinition]) -> list[ToolDefinition]:
    """Apply the same structural model-facing names used by ModelToolNameAdapter."""
    converted: list[ToolDefinition] = []
    seen_names: set[str] = set()
    for definition in tool_definitions:
        schema = deepcopy(definition.input_schema) if isinstance(definition.input_schema, dict) else {}
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
