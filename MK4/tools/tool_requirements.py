from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import json
import sys
from typing import Any

from .. import config
from .llm_client import (
    ChatModel,
    ModelRequestError,
    ModelTurn,
    _compact_tool_history_event,
)
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog
from .tool_runtime import ToolDefinition


_TOOL_REQUIREMENT_INSTRUCTION = """
Decide which currently exposed tools are genuinely required after considering the user's request together with the already supplied automatic memory context.

This is a pre-answer decision. Do not draft the answer and do not invent capabilities.

Process:
1. Treat automatic_memory_context as information that is already available before tool use. It is not a tool execution and does not need to be counted as one.
2. Evaluate every exposed tool exactly once as required=true or required=false.
3. Mark a tool required=true only when it belongs to a minimal way to obtain information or perform an action that is still necessary to honestly complete the user's request.
4. A tool that is merely related, potentially useful, or nice to have is required=false.
5. If already supplied memory fully resolves a stable memory-based question, additional recall tools are not required. If the needed past detail is missing from supplied memory, an explicit recall tool may be required.
6. If the requested fact/state can reasonably differ today from yesterday, stale memory does not satisfy that current-information need; an appropriate current external tool can still be required.
7. After evaluating tools individually, group required=true tools by substitutability:
   - tools in the same group are alternatives; one successful tool in that group is enough for that part of the request,
   - tools that are jointly necessary must be in different groups,
   - a required tool with no substitute forms a one-tool group.
8. Never place a required=false tool in a group. Every required=true tool must appear in exactly one group.
9. Use only tool names present in tool_catalog.

The final required_groups represent AND across groups and OR within each group.
""".strip()

_REQUIREMENT_RETRY_INSTRUCTION = """
The required tool groups for this request were decided before drafting and are frozen for this request.
The proposed response cannot be released because one or more required groups have no successful tool execution in this turn.
For each missing group, use one tool from that group. Do not replace requested execution with instructions for the user.
""".strip()

_RESULT_ADEQUACY_INSTRUCTION = """
Review whether the successful tool results obtained in this turn are sufficient to satisfy the user's actual request.
Judge the tool results themselves, not the wording of a proposed answer.

Rules:
- Use semantic judgment, not keyword matching or tool-name-specific rules.
- Check the user's explicit constraints such as time window, target entity, requested attributes, scope, relevance, and requested level of detail.
- A successful tool call is not automatically adequate. Results may be stale, outside the requested period, irrelevant, incomplete, ambiguous, or too shallow to establish what the user asked for.
- Do not demand information beyond the user's request.
- Do not require a particular next tool. If results are inadequate, identify only the missing aspects that still need to be resolved.
- If the available results already support the requested outcome at the requested level of detail, mark them adequate.
""".strip()

_ADEQUACY_RETRY_INSTRUCTION = """
The required tool group was executed, but the returned results were reviewed as insufficient for the user's request.
Use the exposed tools to resolve the listed missing aspects before answering. Choose the next tool and query based on the actual missing information; do not substitute instructions for the user.
""".strip()


@dataclass(frozen=True, slots=True)
class ToolEvaluation:
    tool: str
    required: bool


@dataclass(frozen=True, slots=True)
class ToolRequirementGroup:
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FrozenToolRequirements:
    evaluations: tuple[ToolEvaluation, ...] = ()
    groups: tuple[ToolRequirementGroup, ...] = ()

    @property
    def required(self) -> bool:
        return bool(self.groups)


@dataclass(frozen=True, slots=True)
class ToolResultAdequacy:
    adequate: bool
    missing_aspects: tuple[str, ...] = ()


_ACTIVE_REQUIREMENTS: ContextVar[FrozenToolRequirements | None] = ContextVar(
    "mk4_active_tool_requirements",
    default=None,
)


def start_tool_requirement_scope() -> Token[FrozenToolRequirements | None]:
    return _ACTIVE_REQUIREMENTS.set(None)


def reset_tool_requirement_scope(token: Token[FrozenToolRequirements | None]) -> None:
    _ACTIVE_REQUIREMENTS.reset(token)


class ToolRequirementGuardChatModel:
    """Freeze tool-by-tool needs, then require both execution and adequate results."""

    def __init__(self, delegate: ChatModel) -> None:
        self._delegate = delegate

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
        requirements = _ACTIVE_REQUIREMENTS.get()
        if requirements is None:
            requirements = await plan_tool_requirements(
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
            )
            _ACTIVE_REQUIREMENTS.set(requirements)
            _debug_requirement_plan(requirements)

        turn = await self._delegate.next_turn(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )
        if turn.tool_calls or not turn.final_answer or turn.final_answer_kind == "blocked":
            return turn

        missing = missing_required_groups(requirements, tool_history)
        if missing:
            _debug_missing_requirements(missing)
            retry_history = [
                *tool_history,
                {
                    "tool": "tool_requirement_guard",
                    "arguments": {},
                    "result": {
                        "ok": False,
                        "error": "frozen_tool_requirement_unmet",
                        "message": _REQUIREMENT_RETRY_INSTRUCTION,
                        "missing_groups": [_group_payload(group) for group in missing],
                        "rejected_response": turn.final_answer[:1000],
                    },
                },
            ]
            retry = await self._delegate.next_turn(
                system=f"{system}\n\n{_REQUIREMENT_RETRY_INSTRUCTION}",
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=retry_history,
            )
            if retry.tool_calls or not retry.final_answer or retry.final_answer_kind == "blocked":
                return retry
            return ModelTurn(
                final_answer="필요한 도구 실행이 완료되지 않아 이 요청의 답변을 확정하지 않았습니다.",
                final_answer_kind="blocked",
            )

        if not requirements.required:
            return turn

        adequacy = await review_tool_result_adequacy(
            system=system,
            user_message=user_message,
            model=model,
            requirements=requirements,
            tool_history=tool_history,
        )
        _debug_adequacy(adequacy)
        if adequacy.adequate:
            return turn

        retry_history = [
            *tool_history,
            {
                "tool": "tool_result_adequacy_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": "tool_results_inadequate",
                    "message": _ADEQUACY_RETRY_INSTRUCTION,
                    "missing_aspects": list(adequacy.missing_aspects),
                    "successful_tool_results": _successful_tool_result_payloads(tool_history),
                },
            },
        ]
        retry = await self._delegate.next_turn(
            system=f"{system}\n\n{_ADEQUACY_RETRY_INSTRUCTION}",
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=retry_history,
        )
        if retry.tool_calls or not retry.final_answer or retry.final_answer_kind == "blocked":
            return retry
        return ModelTurn(
            final_answer="도구 결과가 요청 조건을 충분히 충족하지 않아 답변을 확정하지 않았습니다.",
            final_answer_kind="blocked",
        )


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
            "tool_evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "enum": tool_names},
                        "required": {"type": "boolean"},
                    },
                    "required": ["tool", "required"],
                    "additionalProperties": False,
                },
            },
            "required_groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tools": {
                            "type": "array",
                            "items": {"type": "string", "enum": tool_names},
                            "minItems": 1,
                        },
                    },
                    "required": ["tools"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["tool_evaluations", "required_groups"],
        "additionalProperties": False,
    }
    payload = {
        "user_request": user_message,
        "automatic_memory_context": {
            "source": "automatic_graph_activation",
            "already_available_before_tool_use": True,
            "items": memory_summary,
        },
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
    return _parse_requirement_plan(data, tool_names=tool_names)


def _parse_requirement_plan(data: object, *, tool_names: list[str]) -> FrozenToolRequirements:
    if not isinstance(data, dict):
        raise RuntimeError("Tool requirement plan must be an object.")
    evaluations_raw = data.get("tool_evaluations")
    groups_raw = data.get("required_groups")
    if not isinstance(evaluations_raw, list):
        raise RuntimeError("Tool requirement plan must contain tool_evaluations list.")
    if not isinstance(groups_raw, list):
        raise RuntimeError("Tool requirement plan must contain required_groups list.")

    available = set(tool_names)
    evaluations: list[ToolEvaluation] = []
    seen_tools: set[str] = set()
    for index, item in enumerate(evaluations_raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"tool_evaluations[{index}] must be an object.")
        tool = str(item.get("tool") or "").strip()
        required = item.get("required")
        if tool not in available:
            raise RuntimeError(f"tool_evaluations[{index}] contains unavailable tool: {tool}")
        if tool in seen_tools:
            raise RuntimeError(f"Duplicate tool evaluation: {tool}")
        if not isinstance(required, bool):
            raise RuntimeError(f"tool_evaluations[{index}].required must be boolean.")
        seen_tools.add(tool)
        evaluations.append(ToolEvaluation(tool=tool, required=required))

    if seen_tools != available:
        missing = sorted(available - seen_tools)
        extra = sorted(seen_tools - available)
        raise RuntimeError(
            "Tool requirement plan must evaluate every exposed tool exactly once. "
            f"missing={missing} extra={extra}"
        )

    required_tools = {item.tool for item in evaluations if item.required}
    grouped_tools: set[str] = set()
    groups: list[ToolRequirementGroup] = []
    for index, item in enumerate(groups_raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"required_groups[{index}] must be an object.")
        tools = item.get("tools")
        if not isinstance(tools, list) or not tools:
            raise RuntimeError(f"required_groups[{index}].tools must be a non-empty list.")
        normalized = tuple(dict.fromkeys(str(name).strip() for name in tools if str(name).strip()))
        if len(normalized) != len(tools):
            raise RuntimeError(f"required_groups[{index}] contains duplicate or empty tool names.")
        unknown = [name for name in normalized if name not in available]
        if unknown:
            raise RuntimeError(f"required_groups[{index}] contains unavailable tools: {unknown}")
        false_tools = [name for name in normalized if name not in required_tools]
        if false_tools:
            raise RuntimeError(
                f"required_groups[{index}] contains tools evaluated required=false: {false_tools}"
            )
        duplicates = [name for name in normalized if name in grouped_tools]
        if duplicates:
            raise RuntimeError(f"Required tools may appear in only one group: {duplicates}")
        grouped_tools.update(normalized)
        groups.append(ToolRequirementGroup(tools=normalized))

    if grouped_tools != required_tools:
        missing = sorted(required_tools - grouped_tools)
        extra = sorted(grouped_tools - required_tools)
        raise RuntimeError(
            "Every required=true tool must appear in exactly one required group and no required=false tool may appear. "
            f"missing={missing} extra={extra}"
        )

    return FrozenToolRequirements(
        evaluations=tuple(evaluations),
        groups=tuple(groups),
    )


async def review_tool_result_adequacy(
    *,
    system: str,
    user_message: str,
    model: str | None,
    requirements: FrozenToolRequirements,
    tool_history: list[dict[str, Any]],
) -> ToolResultAdequacy:
    response_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "adequate": {"type": "boolean"},
            "missing_aspects": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
            },
        },
        "required": ["adequate", "missing_aspects"],
        "additionalProperties": False,
    }
    payload = {
        "user_request": user_message,
        "frozen_required_groups": [_group_payload(group) for group in requirements.groups],
        "successful_tool_results": _successful_tool_result_payloads(tool_history),
    }
    try:
        raw = await ollama_chat(
            system=f"{system}\n\n{_RESULT_ADEQUACY_INSTRUCTION}",
            user=json.dumps(payload, ensure_ascii=False),
            model=model,
            response_format=response_schema,
        )
    except ValueError as exc:
        raise ModelRequestError(str(exc)) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Tool result adequacy review must be valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("adequate"), bool):
        raise RuntimeError("Tool result adequacy review must contain boolean adequate.")
    missing = data.get("missing_aspects")
    if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
        raise RuntimeError("Tool result adequacy review missing_aspects must be a list of strings.")
    cleaned = tuple(dict.fromkeys(item.strip() for item in missing if item.strip()))
    if data["adequate"] is False and not cleaned:
        raise RuntimeError("Inadequate tool result review must explain at least one missing aspect.")
    return ToolResultAdequacy(adequate=data["adequate"], missing_aspects=cleaned)


def missing_required_groups(
    requirements: FrozenToolRequirements,
    tool_history: list[dict[str, Any]],
) -> list[ToolRequirementGroup]:
    successful_tools = {
        str(event.get("tool") or "").strip()
        for event in tool_history
        if _event_succeeded(event)
    }
    return [
        group
        for group in requirements.groups
        if not successful_tools.intersection(group.tools)
    ]


def _successful_tool_result_payloads(tool_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _compact_tool_history_event(event)
        for event in tool_history
        if _event_succeeded(event)
    ]


def _event_succeeded(event: dict[str, Any]) -> bool:
    result = event.get("result")
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return False
    if "returncode" in result and result.get("returncode") not in {None, 0}:
        return False
    return event.get("tool") not in {
        "execution_guard",
        "evidence_grounding_guard",
        "tool_requirement_guard",
        "tool_result_adequacy_guard",
        "autonomy_guard",
        "file_text_activation",
    }


def _group_payload(group: ToolRequirementGroup) -> dict[str, Any]:
    return {"tools": list(group.tools)}


def _debug_requirement_plan(requirements: FrozenToolRequirements) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    true_tools = [item.tool for item in requirements.evaluations if item.required]
    groups = " AND ".join(
        f"({' OR '.join(group.tools)})"
        for group in requirements.groups
    ) or "none"
    print(
        f"[MK4 requirement] required_tools={','.join(true_tools) or 'none'} groups={groups}",
        file=sys.stderr,
        flush=True,
    )


def _debug_missing_requirements(missing: list[ToolRequirementGroup]) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    text = " AND ".join(f"({' OR '.join(group.tools)})" for group in missing)
    print(f"[MK4 requirement] unmet_groups={text}", file=sys.stderr, flush=True)


def _debug_adequacy(adequacy: ToolResultAdequacy) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    missing = " | ".join(adequacy.missing_aspects) if adequacy.missing_aspects else "none"
    print(
        f"[MK4 adequacy] adequate={str(adequacy.adequate).lower()} missing={missing}",
        file=sys.stderr,
        flush=True,
    )
