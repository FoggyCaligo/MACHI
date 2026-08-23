from __future__ import annotations

from copy import deepcopy
from time import perf_counter

from .compact_requirement_planner import plan_compact_tool_requirements
from .debug_timing import log_timing
from .tool_requirements import (
    FrozenToolRequirements,
    freeze_tool_requirements,
    _debug_requirement_plan,
)
from .tool_runtime import ToolDefinition


async def plan_and_freeze_before_memory(
    *,
    user_message: str,
    recent_dialogue_pairs: list[dict[str, str]],
    model: str | None,
    tool_definitions: list[ToolDefinition],
) -> FrozenToolRequirements:
    """Plan exact required tool executions from recent dialogue plus the current user input, then freeze them."""
    model_definitions = model_facing_definitions(tool_definitions)
    started = perf_counter()
    try:
        requirements = await plan_compact_tool_requirements(
            user_message=user_message,
            recent_dialogue_pairs=recent_dialogue_pairs,
            model=model,
            tool_definitions=model_definitions,
        )
    finally:
        log_timing("requirement_planner", perf_counter() - started)
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
