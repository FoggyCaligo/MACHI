from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import json
import sys
from typing import Any

from .. import config
from .llm_client import ChatModel, ModelRequestError, ModelTurn
from .ollama_client import chat as ollama_chat
from .tool_catalog import compact_tool_catalog
from .tool_requirements import (
    _REQUIREMENT_RETRY_INSTRUCTION,
    _debug_adequacy,
    _debug_missing_requirements,
    _debug_requirement_plan,
    _parse_requirement_plan,
    _successful_tool_result_payloads,
    freeze_tool_requirements,
    get_frozen_tool_requirements,
    missing_required_tools,
    plan_tool_requirements,
    review_tool_result_adequacy,
    FrozenToolRequirements,
    ToolRequirementPlanError,
)
from .tool_runtime import ToolDefinition


_RECOVERY_TOOL_PLAN_INSTRUCTION = """
Decide which currently exposed tools must actually be executed next to resolve the evidence gaps identified by the result-adequacy review.

This is a recovery tool-requirement decision only. Do not draft the answer and do not write tool arguments or search queries.

Rules:
1. The response schema contains one boolean property for every exposed tool. Judge every property independently as true or false.
2. true means that exact tool must be successfully executed after this recovery decision before the missing aspects can be considered addressed.
3. false means that exact tool is not required for this recovery step.
4. There is no OR/substitution grouping. If multiple tools are true, all of them must execute successfully.
5. Select at least one tool because the adequacy reviewer has already determined that the current evidence is insufficient.
6. Base the decision on the user's request, the unresolved missing aspects, the successful tool results already obtained, and the exposed tool catalog.
7. Do not choose tools merely because they are available. Choose only tools whose execution can make concrete progress on the missing aspects.
8. Do not invent capabilities and do not infer tool use from string or keyword rules.
""".strip()

_RECOVERY_REQUIRED_TOOL_INSTRUCTION = """
The evidence-recovery planner has frozen exact tool requirements for the current recovery step.
A final answer cannot be released until every tool listed in recovery_missing_tools has a new successful execution after this recovery step began.
Execute the listed tools now. Choose the arguments and queries yourself from the user's request and the unresolved missing aspects.
Do not replace execution with an answer, explanation, or instructions for the user.
""".strip()

_ADEQUACY_SCOPE_LOCK_INSTRUCTION = """
The result-adequacy review is scope-locked to the user's actual request.

When deciding adequacy or writing missing_aspects:
- Preserve the requested target, product/category, task, constraints, and requested output form.
- missing_aspects may describe only facts, attributes, evidence, or distinctions that are actually needed to answer that request.
- Do not replace the requested target with a safer, easier, broader, narrower, or different alternative.
- Do not add a new deliverable that the user did not request.
- Do not turn cautionary advice, professional consultation, or an alternative product/category into a missing requirement unless the user explicitly asked for that consultation or alternative.
- Safety or uncertainty may affect how confidently the eventual answer is phrased, but they do not authorize redefining what the user asked for.
- If the evidence is insufficient for the requested answer, identify the missing evidence needed for that same requested answer.
""".strip()

_MAX_RECOVERY_CYCLES = 3


@dataclass(frozen=True, slots=True)
class RecoveryState:
    cycles_started: int = 0
    requirements: FrozenToolRequirements | None = None
    baseline_history_len: int = 0
    missing_aspects: tuple[str, ...] = ()
    reviewed_evidence_version: int = -1


_ACTIVE_RECOVERY: ContextVar[RecoveryState | None] = ContextVar(
    "mk4_active_adequacy_recovery",
    default=None,
)


def start_recovery_scope() -> Token[RecoveryState | None]:
    return _ACTIVE_RECOVERY.set(RecoveryState())


def reset_recovery_scope(token: Token[RecoveryState | None]) -> None:
    _ACTIVE_RECOVERY.reset(token)


def get_recovery_state() -> RecoveryState:
    return _ACTIVE_RECOVERY.get() or RecoveryState()


def _set_recovery_state(state: RecoveryState) -> None:
    _ACTIVE_RECOVERY.set(state)


def _evidence_version(tool_history: list[dict[str, Any]]) -> int:
    return len(_successful_tool_result_payloads(tool_history))


async def plan_recovery_tool_requirements(
    *,
    user_message: str,
    missing_aspects: tuple[str, ...],
    successful_tool_results: list[dict[str, Any]],
    model: str | None,
    tool_definitions: list[ToolDefinition],
    recovery_attempt: int,
) -> FrozenToolRequirements:
    if not tool_definitions:
        raise ToolRequirementPlanError(
            "Evidence recovery requires at least one exposed tool, but no tools are available."
        )

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
        "missing_aspects": list(missing_aspects),
        "successful_tool_results": successful_tool_results,
        "tool_catalog": compact_tool_catalog(tool_definitions),
        "recovery_attempt": recovery_attempt,
        "max_recovery_attempts": _MAX_RECOVERY_CYCLES,
    }
    try:
        raw = await ollama_chat(
            system=_RECOVERY_TOOL_PLAN_INSTRUCTION,
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
        if isinstance(exc, json.JSONDecodeError):
            raise ToolRequirementPlanError(
                f"Recovery tool requirement plan must be valid JSON: {exc}"
            ) from exc
        raise

    if not requirements.required:
        raise ToolRequirementPlanError(
            "Recovery tool requirement plan must require at least one exposed tool when evidence is inadequate."
        )
    return requirements


class RecoveringToolRequirementGuardChatModel:
    """Frozen requirement guard with bounded, planner-driven evidence recovery."""

    def __init__(self, delegate: ChatModel, *, max_recovery_cycles: int = _MAX_RECOVERY_CYCLES) -> None:
        self._delegate = delegate
        self._max_recovery_cycles = max(1, max_recovery_cycles)

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
        requirements = get_frozen_tool_requirements()
        if requirements is None:
            requirements = await plan_tool_requirements(
                user_message=user_message,
                model=model,
                tool_definitions=tool_definitions,
            )
            freeze_tool_requirements(requirements)
            _debug_requirement_plan(requirements)

        recovery = get_recovery_state()
        if recovery.requirements is not None:
            recovery_history = tool_history[recovery.baseline_history_len:]
            recovery_missing = missing_required_tools(recovery.requirements, recovery_history)
            if recovery_missing:
                return await self._request_recovery_tools(
                    system=system,
                    user_message=user_message,
                    model=model,
                    memory_summary=memory_summary,
                    tool_definitions=tool_definitions,
                    tool_history=tool_history,
                    recovery=recovery,
                    recovery_missing=recovery_missing,
                )
            _set_recovery_state(
                RecoveryState(
                    cycles_started=recovery.cycles_started,
                    reviewed_evidence_version=recovery.reviewed_evidence_version,
                )
            )

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

        evidence_version = _evidence_version(tool_history)
        recovery = get_recovery_state()
        if (
            recovery.requirements is None
            and recovery.missing_aspects
            and recovery.reviewed_evidence_version == evidence_version
        ):
            _debug_reused_inadequacy(recovery)
            return await self._plan_and_request_recovery(
                system=system,
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=tool_history,
                recovery=recovery,
            )

        adequacy = await review_tool_result_adequacy(
            system=f"{system}\n\n{_ADEQUACY_SCOPE_LOCK_INSTRUCTION}",
            user_message=user_message,
            model=model,
            requirements=requirements,
            tool_history=tool_history,
        )
        _debug_adequacy(adequacy)
        if adequacy.adequate:
            _set_recovery_state(
                RecoveryState(
                    cycles_started=recovery.cycles_started,
                    reviewed_evidence_version=evidence_version,
                )
            )
            return turn

        pending = RecoveryState(
            cycles_started=recovery.cycles_started,
            missing_aspects=adequacy.missing_aspects,
            reviewed_evidence_version=evidence_version,
        )
        _set_recovery_state(pending)
        return await self._plan_and_request_recovery(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
            recovery=pending,
        )

    async def _plan_and_request_recovery(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
        recovery: RecoveryState,
    ) -> ModelTurn:
        if recovery.cycles_started >= self._max_recovery_cycles:
            return ModelTurn(
                final_answer=(
                    f"추가 근거 확보를 {self._max_recovery_cycles}회 시도했지만 요청 조건을 "
                    "충분히 충족하지 못해 답변을 확정하지 않았습니다."
                ),
                final_answer_kind="blocked",
            )

        next_cycle = recovery.cycles_started + 1
        recovery_requirements = await plan_recovery_tool_requirements(
            user_message=user_message,
            missing_aspects=recovery.missing_aspects,
            successful_tool_results=_successful_tool_result_payloads(tool_history),
            model=model,
            tool_definitions=tool_definitions,
            recovery_attempt=next_cycle,
        )
        active = RecoveryState(
            cycles_started=next_cycle,
            requirements=recovery_requirements,
            baseline_history_len=len(tool_history),
            missing_aspects=recovery.missing_aspects,
            reviewed_evidence_version=recovery.reviewed_evidence_version,
        )
        _set_recovery_state(active)
        _debug_recovery_plan(active)
        return await self._request_recovery_tools(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
            recovery=active,
            recovery_missing=recovery_requirements.required_tools,
        )

    async def _request_recovery_tools(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
        recovery: RecoveryState,
        recovery_missing: tuple[str, ...],
    ) -> ModelTurn:
        guard_event = {
            "tool": "tool_result_adequacy_guard",
            "arguments": {},
            "result": {
                "ok": False,
                "error": "evidence_recovery_tool_required",
                "message": _RECOVERY_REQUIRED_TOOL_INSTRUCTION,
                "recovery_attempt": recovery.cycles_started,
                "max_recovery_attempts": self._max_recovery_cycles,
                "recovery_missing_tools": list(recovery_missing),
                "missing_aspects": list(recovery.missing_aspects),
            },
        }
        retry_history = [*tool_history, guard_event]
        retry_system = f"{system}\n\n{_RECOVERY_REQUIRED_TOOL_INSTRUCTION}"
        retry = await self._delegate.next_turn(
            system=retry_system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=retry_history,
        )
        if retry.tool_calls or not retry.final_answer:
            return retry

        retry_history = [
            *retry_history,
            {
                "tool": "tool_result_adequacy_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": "evidence_recovery_tool_unmet",
                    "message": _RECOVERY_REQUIRED_TOOL_INSTRUCTION,
                    "recovery_attempt": recovery.cycles_started,
                    "recovery_missing_tools": list(recovery_missing),
                    "missing_aspects": list(recovery.missing_aspects),
                    "rejected_response": (retry.final_answer or "")[:1000],
                },
            },
        ]
        second = await self._delegate.next_turn(
            system=retry_system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=retry_history,
        )
        if second.tool_calls or not second.final_answer:
            return second
        return ModelTurn(
            final_answer="추가 근거 확보에 필요한 도구가 선택되었지만 실제 실행이 이루어지지 않아 답변을 확정하지 않았습니다.",
            final_answer_kind="blocked",
        )


def _debug_recovery_plan(recovery: RecoveryState) -> None:
    if not config.AGENT_DEBUG_LOG or recovery.requirements is None:
        return
    print(
        "[MK4 recovery] "
        f"attempt={recovery.cycles_started}/{_MAX_RECOVERY_CYCLES} "
        f"required_tools={','.join(recovery.requirements.required_tools)}",
        file=sys.stderr,
        flush=True,
    )


def _debug_reused_inadequacy(recovery: RecoveryState) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    missing = " | ".join(recovery.missing_aspects) if recovery.missing_aspects else "none"
    print(
        "[MK4 adequacy] reuse_previous_inadequate=true "
        f"evidence_version={recovery.reviewed_evidence_version} missing={missing}",
        file=sys.stderr,
        flush=True,
    )
