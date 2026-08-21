from __future__ import annotations

from typing import Any

from .tool_runtime import ToolDefinition, ToolRegistry


_RESEARCH_TOOLS = {"latest_search", "web_research"}
_MAX_STEPS = 8


class ResearchPlanToolSuite:
    """Persist a model-authored research plan in tool history.

    Each step is a claim-oriented unit of work. The orchestrator later enforces
    the declared tool order and requires every planned step to finish before a
    final answer can be accepted.
    """

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="research_plan",
                description=(
                    "Create the ordered claim-oriented work plan that must be followed before factual web research. "
                    "Use this before latest_search or web_research. Each step states one claim/objective to verify, "
                    "the web tool to use for that step, and dependencies on earlier step IDs. Do not include tool arguments here; "
                    "form the actual tool arguments when executing each step after consulting the tool manual."
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
                                    "tool": {"type": "string", "enum": sorted(_RESEARCH_TOOLS)},
                                    "depends_on": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "maxItems": _MAX_STEPS,
                                    },
                                },
                                "required": ["step_id", "claim", "tool", "depends_on"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["goal", "steps"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    async def _run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        goal = str(arguments.get("goal") or "").strip()
        steps_raw = arguments.get("steps")
        if not goal:
            raise ValueError("research_plan requires goal")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("research_plan requires at least one step")
        if len(steps_raw) > _MAX_STEPS:
            raise ValueError(f"research_plan supports at most {_MAX_STEPS} steps")

        steps: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(steps_raw):
            if not isinstance(raw, dict):
                raise ValueError(f"research_plan.steps[{index}] must be an object")
            step_id = str(raw.get("step_id") or "").strip()
            claim = str(raw.get("claim") or "").strip()
            tool = str(raw.get("tool") or "").strip()
            depends_raw = raw.get("depends_on")
            if not step_id:
                raise ValueError(f"research_plan.steps[{index}].step_id is required")
            if step_id in seen_ids:
                raise ValueError(f"research_plan step_id must be unique: {step_id}")
            if not claim:
                raise ValueError(f"research_plan.steps[{index}].claim is required")
            if tool not in _RESEARCH_TOOLS:
                raise ValueError(f"unsupported research plan tool: {tool}")
            if not isinstance(depends_raw, list) or not all(isinstance(item, str) for item in depends_raw):
                raise ValueError(f"research_plan.steps[{index}].depends_on must be a list of step IDs")
            depends_on = [item.strip() for item in depends_raw if item.strip()]
            missing_dependencies = [item for item in depends_on if item not in seen_ids]
            if missing_dependencies:
                raise ValueError(
                    f"research_plan step {step_id} depends on unknown or later steps: {missing_dependencies}"
                )
            seen_ids.add(step_id)
            steps.append({
                "step_id": step_id,
                "claim": claim,
                "tool": tool,
                "depends_on": depends_on,
            })

        return {
            "ok": True,
            "goal": goal,
            "steps": steps,
        }
