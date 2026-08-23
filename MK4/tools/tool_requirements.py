from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .llm_client import ModelRequestError
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog
from .tool_runtime import ToolDefinition


_TOOL_REQUIREMENT_INSTRUCTION = """
Decide only whether the user's request requires one or more exposed tool capabilities to be actually executed before a final response can honestly satisfy the request.

This is a pre-answer decision. Do not draft the answer.

Rules:
- Use the meaning of the user's request, not keyword matching.
- A tool is required when the requested result itself depends on performing an external action, retrieval, inspection, search, recall beyond already supplied automatic memory, or state change.
- Read-only exploration may be required even when the model could instead give instructions; if the user asked for the result of a search/read/inspection, the corresponding capability is required.
- If automatic_memory_context already contains enough information for a broad memory response, explicit memory recall need not be required. If the request asks for past details not established by that supplied context, persistent recall may be required.
- Stable conceptual explanations that can be answered directly do not require tools merely because related tools exist.
- For each requirement, name a short semantic capability and select every currently exposed tool that could validly satisfy that capability for this request.
- Never invent tool names. Use only names present in tool_catalog.
- Keep requirements minimal. Different capabilities may be required together when the task genuinely needs both.
""".strip()


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    capability: str
    satisfying_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FrozenToolRequirements:
    requirements: tuple[ToolRequirement, ...] = ()

    @property
    def required(self) -> bool:
        return bool(self.requirements)


async def plan_tool_requirements(
    *,
    user_message: str,
    model: str | None,
    memory_summary: list[Any],
    tool_definitions: list[ToolDefinition],
) -> FrozenToolRequirements:
    if not tool_definitions:
        return FrozenToolRequirements()

    tool_names = sorted({definition.name for definition in tool_definitions})
    response_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "capability": {"type": "string"},
                        "satisfying_tools": {
                            "type": "array",
                            "items": {"type": "string", "enum": tool_names},
                        },
                    },
                    "required": ["capability", "satisfying_tools"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["requirements"],
        "additionalProperties": False,
    }
    payload = {
        "user_message": user_message,
        "automatic_memory_context": memory_summary,
        "tool_catalog": compact_tool_catalog(tool_definitions),
    }
    try:
        raw = await ollama_chat(
            system=_TOOL_REQUIREMENT_INSTRUCTION,
            user=json.dumps(payload, ensure_ascii=False),
            model=model,
            response_format=response_schema,
        )
    except ValueError as exc:
        raise ModelRequestError(str(exc)) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Tool requirement plan must be valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("requirements"), list):
        raise RuntimeError("Tool requirement plan must contain a requirements list.")

    available = set(tool_names)
    requirements: list[ToolRequirement] = []
    seen_capabilities: set[str] = set()
    for index, item in enumerate(data["requirements"]):
        if not isinstance(item, dict):
            raise RuntimeError(f"requirements[{index}] must be an object.")
        capability = str(item.get("capability") or "").strip()
        tools = item.get("satisfying_tools")
        if not capability:
            raise RuntimeError(f"requirements[{index}].capability must be non-empty.")
        if not isinstance(tools, list) or not tools:
            raise RuntimeError(f"requirements[{index}].satisfying_tools must be a non-empty list.")
        normalized_tools = tuple(dict.fromkeys(str(name).strip() for name in tools if str(name).strip()))
        if not normalized_tools or any(name not in available for name in normalized_tools):
            raise RuntimeError(f"requirements[{index}] contains unavailable tool names.")
        if capability in seen_capabilities:
            raise RuntimeError(f"Duplicate required capability: {capability}")
        seen_capabilities.add(capability)
        requirements.append(ToolRequirement(capability=capability, satisfying_tools=normalized_tools))

    return FrozenToolRequirements(requirements=tuple(requirements))


def missing_required_capabilities(
    requirements: FrozenToolRequirements,
    tool_history: list[dict[str, Any]],
) -> list[ToolRequirement]:
    successful_tools = {
        str(event.get("tool") or "").strip()
        for event in tool_history
        if _event_succeeded(event)
    }
    return [
        requirement
        for requirement in requirements.requirements
        if not successful_tools.intersection(requirement.satisfying_tools)
    ]


def _event_succeeded(event: dict[str, Any]) -> bool:
    result = event.get("result")
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return False
    if "returncode" in result and result.get("returncode") not in {None, 0}:
        return False
    return event.get("tool") not in {"execution_guard", "evidence_grounding_guard", "autonomy_guard", "file_text_activation"}
