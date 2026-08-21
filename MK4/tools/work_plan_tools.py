from __future__ import annotations

from typing import Any

from .tool_runtime import ToolDefinition, ToolRegistry


_MAX_STEPS = 10
_ACTION_TYPES = {"reasoning", "tool"}
_RESERVED_PLAN_TOOLS = {"work_plan", "work_step_complete", "tool_manual"}


class WorkPlanToolSuite:
    """Expose a universal ordered work plan and explicit reasoning-step completion."""

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="work_plan",
                description=(
                    "Create the ordered work plan for the current user request before doing the work. "
                    "Each step is one claim-oriented unit that must be completed in order. Use action_type='tool' "
                    "when a concrete tool must run, or action_type='reasoning' when the step is internal analysis. "
                    "For tool steps, set tool to the exact model-visible tool name. For reasoning steps, set tool to null. "
                    "Do not include tool arguments in the plan; form them when executing that step after reading any needed manual."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "steps": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": _MAX_STEPS,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step_id": {"type": "string"},
                                    "claim": {"type": "string"},
                                    "action_type": {
                                        "type": "string",
                                        "enum": sorted(_ACTION_TYPES),
                                    },
                                    "tool": {"type": ["string", "null"]},
                                    "depends_on": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "maxItems": _MAX_STEPS,
                                    },
                                },
                                "required": ["step_id", "claim", "action_type", "tool", "depends_on"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["goal", "steps"],
                    "additionalProperties": False,
                },
            ),
            self._run_plan,
        )
        registry.register(
            ToolDefinition(
                name="work_step_complete",
                description=(
                    "Complete the current reasoning step from work_plan. Use only for a reasoning step, "
                    "with that exact step_id and a concise conclusion established by the reasoning."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "step_id": {"type": "string"},
                        "conclusion": {"type": "string"},
                    },
                    "required": ["step_id", "conclusion"],
                    "additionalProperties": False,
                },
            ),
            self._run_step_complete,
        )
        return registry

    async def _run_plan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        goal = str(arguments.get("goal") or "").strip()
        steps_raw = arguments.get("steps")
        if not goal:
            raise ValueError("work_plan requires goal")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("work_plan requires at least one step")
        if len(steps_raw) > _MAX_STEPS:
            raise ValueError(f"work_plan supports at most {_MAX_STEPS} steps")

        steps: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(steps_raw):
            if not isinstance(raw, dict):
                raise ValueError(f"work_plan.steps[{index}] must be an object")
            step_id = str(raw.get("step_id") or "").strip()
            claim = str(raw.get("claim") or "").strip()
            action_type = str(raw.get("action_type") or "").strip()
            tool_raw = raw.get("tool")
            tool = str(tool_raw).strip() if tool_raw is not None else None
            depends_raw = raw.get("depends_on")

            if not step_id:
                raise ValueError(f"work_plan.steps[{index}].step_id is required")
            if step_id in seen_ids:
                raise ValueError(f"work_plan step_id must be unique: {step_id}")
            if not claim:
                raise ValueError(f"work_plan.steps[{index}].claim is required")
            if action_type not in _ACTION_TYPES:
                raise ValueError(f"unsupported work_plan action_type: {action_type}")
            if action_type == "tool" and not tool:
                raise ValueError(f"work_plan.steps[{index}].tool is required for tool steps")
            if action_type == "tool" and tool in _RESERVED_PLAN_TOOLS:
                raise ValueError(f"work_plan meta tool cannot be a planned work step: {tool}")
            if action_type == "reasoning" and tool is not None:
                raise ValueError(f"work_plan.steps[{index}].tool must be null for reasoning steps")
            if not isinstance(depends_raw, list) or not all(isinstance(item, str) for item in depends_raw):
                raise ValueError(f"work_plan.steps[{index}].depends_on must be a list of step IDs")
            depends_on = [item.strip() for item in depends_raw if item.strip()]
            missing_dependencies = [item for item in depends_on if item not in seen_ids]
            if missing_dependencies:
                raise ValueError(
                    f"work_plan step {step_id} depends on unknown or later steps: {missing_dependencies}"
                )

            seen_ids.add(step_id)
            steps.append({
                "step_id": step_id,
                "claim": claim,
                "action_type": action_type,
                "tool": tool,
                "depends_on": depends_on,
            })

        return {"ok": True, "goal": goal, "steps": steps}

    async def _run_step_complete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        step_id = str(arguments.get("step_id") or "").strip()
        conclusion = str(arguments.get("conclusion") or "").strip()
        if not step_id:
            raise ValueError("work_step_complete requires step_id")
        if not conclusion:
            raise ValueError("work_step_complete requires conclusion")
        return {
            "ok": True,
            "step_id": step_id,
            "conclusion": conclusion,
        }
