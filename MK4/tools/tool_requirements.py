from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime
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
Decide which currently exposed tools must actually be executed to honestly complete the user's request.

This decision is about required tool execution, not answer drafting. Judge only the user's request, the current date, and the exposed tool catalog. Do not assume that automatic memory supplied later will satisfy a required tool execution.

Rules:
1. The response schema contains one boolean property for every exposed tool. Judge every property independently as true or false.
2. true means that exact tool must be successfully executed for this request before a final answer may be released.
3. false means that exact tool is not required. A tool that is merely related, potentially useful, or nice to have is false.
4. There is no OR/substitution grouping. If two tools are both true, both must be successfully executed.
5. Persistent-memory recall is for retrieving the user's past conversation, preferences, decisions, recommendations, and project context. If the request requires such past information, recall may be true even though automatic memory will be supplied later.
6. Automatic memory supplied later is framework context, not a successful explicit tool execution. It never satisfies a frozen recall requirement.
7. Public or external facts whose truth can reasonably differ today from yesterday require an appropriate current external tool. Persistent memory is not a refresh mechanism for those facts.
8. Stable conceptual explanations that require no retrieval or action remain tool-free.
9. Do not invent capabilities. Use only tools present in the response schema/tool catalog.
""".strip()

_REQUIREMENT_RETRY_INSTRUCTION = """
The required tools for this request were decided before answer drafting and are frozen for this request.
The proposed response cannot be released because one or more required tools have no successful execution in this turn.
Execute every tool listed in missing_tools. Do not replace requested execution with instructions for the user, and do not treat automatic memory as an explicit tool execution.
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
The frozen required tools were executed, but the returned results were reviewed as insufficient for the user's request.
Use the exposed tools to resolve the listed missing aspects before answering. Choose the next tool and query based on the actual missing information; do not substitute instructions for the user.
""".strip()


class ToolRequirementPlanError(RuntimeError):
    """The tool-necessity preflight violated its structured output contract."""


@dataclass(frozen=True, slots=True)
class ToolEvaluation:
    tool: str
    required: bool


@dataclass(frozen=True, slots=True)
class FrozenToolRequirements:
    evaluations: tuple[ToolEvaluation, ...] = ()

    @property
    def required_tools(self) -> tuple[str, ...]:
        return tuple(item.tool for item in self.evaluations if item.required)

    @property
    def required(self) -> bool:
        return bool(self.required_tools)


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


def freeze_tool_requirements(requirements: FrozenToolRequirements) -> None:
    _ACTIVE_REQUIREMENTS.set(requirements)


class ToolRequirementGuardChatModel:
    """Require frozen tools to execute successfully, then require adequate results."""

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
                tool_definitions=tool_definitions,
            )
            freeze_tool_requirements(requirements)
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

        missing = missing_required_tools(requirements, tool_history)
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
                        "missing_tools": list(missing),
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
        return _parse_requirement_plan(data, tool_names=tool_names)
    except (json.JSONDecodeError, ToolRequirementPlanError) as exc:
        error = (
            ToolRequirementPlanError(f"Tool requirement plan must be valid JSON: {exc}")
            if isinstance(exc, json.JSONDecodeError)
            else exc
        )
        _debug_requirement_plan_error(raw=raw, error=error)
        raise error


def _parse_requirement_plan(data: object, *, tool_names: list[str]) -> FrozenToolRequirements:
    if not isinstance(data, dict):
        raise ToolRequirementPlanError("Tool requirement plan must be an object.")
    requirements_raw = data.get("tool_requirements")
    if not isinstance(requirements_raw, dict):
        raise ToolRequirementPlanError("Tool requirement plan must contain tool_requirements object.")

    available = set(tool_names)
    returned_tools = set(requirements_raw)
    if returned_tools != available:
        missing = sorted(available - returned_tools)
        extra = sorted(returned_tools - available)
        raise ToolRequirementPlanError(
            "Tool requirement plan must evaluate every exposed tool exactly once. "
            f"missing={missing} extra={extra}"
        )

    evaluations: list[ToolEvaluation] = []
    for tool in tool_names:
        required = requirements_raw.get(tool)
        if not isinstance(required, bool):
            raise ToolRequirementPlanError(f"tool_requirements.{tool} must be boolean.")
        evaluations.append(ToolEvaluation(tool=tool, required=required))
    return FrozenToolRequirements(evaluations=tuple(evaluations))


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
        "frozen_required_tools": list(requirements.required_tools),
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


def missing_required_tools(
    requirements: FrozenToolRequirements,
    tool_history: list[dict[str, Any]],
) -> tuple[str, ...]:
    successful_tools = {
        str(event.get("tool") or "").strip()
        for event in tool_history
        if _event_succeeded(event)
    }
    return tuple(tool for tool in requirements.required_tools if tool not in successful_tools)


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


def _debug_requirement_plan(requirements: FrozenToolRequirements) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    print(
        f"[MK4 requirement] required_tools={','.join(requirements.required_tools) or 'none'}",
        file=sys.stderr,
        flush=True,
    )


def _debug_requirement_plan_error(*, raw: str, error: Exception) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    limit = max(0, config.MODEL_FAILURE_PREVIEW_CHARS)
    preview = raw[:limit] if limit else "<disabled>"
    print(
        f"[MK4 requirement] plan_error={error!r} raw_chars={len(raw)} raw_preview={preview!r}",
        file=sys.stderr,
        flush=True,
    )


def _debug_missing_requirements(missing: tuple[str, ...]) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    print(
        f"[MK4 requirement] unmet_tools={','.join(missing) or 'none'}",
        file=sys.stderr,
        flush=True,
    )


def _debug_adequacy(adequacy: ToolResultAdequacy) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    missing = " | ".join(adequacy.missing_aspects) if adequacy.missing_aspects else "none"
    print(
        f"[MK4 adequacy] adequate={str(adequacy.adequate).lower()} missing={missing}",
        file=sys.stderr,
        flush=True,
    )
