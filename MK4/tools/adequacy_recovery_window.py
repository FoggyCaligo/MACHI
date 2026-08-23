from __future__ import annotations

import asyncio
import json
import sys
from time import perf_counter
from typing import Any

from .. import config
from .adequacy_recovery import (
    _ADEQUACY_SCOPE_LOCK_INSTRUCTION,
    RecoveringToolRequirementGuardChatModel,
    RecoveryState,
    _debug_reused_inadequacy,
    _evidence_version,
    _set_recovery_state,
    get_recovery_state,
)
from .debug_timing import log_timing
from .grounding_tools import review_final_grounding, store_precomputed_grounding_review
from .llm_client import ModelTurn
from .relaxed_adequacy import review_relaxed_tool_result_adequacy
from .tool_requirements import (
    _REQUIREMENT_RETRY_INSTRUCTION,
    _debug_adequacy,
    _debug_missing_requirements,
    _debug_requirement_plan,
    freeze_tool_requirements,
    get_frozen_tool_requirements,
    missing_required_tools,
    plan_tool_requirements,
)
from .tool_runtime import ToolDefinition


_RECOVERY_EXPLORATION_INSTRUCTION = """
The current evidence-recovery cycle remains active after its frozen minimum tool requirements have succeeded.
A successful recovery-tool execution does not by itself end the recovery cycle.

Continue investigating the unresolved missing aspects with the exposed read/search/inspection tools as many times as materially useful. You may reuse a tool with different arguments when another query or source can add relevant evidence, and you may use other exposed tools when they can help.

Do not call tools merely to increase a count. Stop exploring when the available evidence is good enough to answer the user's original request without a material error. Do not continue merely to make the answer more comprehensive, polished, deeply compared, or broadly sourced. Then return a final answer. A final answer triggers the result-adequacy review, and only an adequate review closes the recovery cycle.
""".strip()


class RecoveryExplorationWindowChatModel(RecoveringToolRequirementGuardChatModel):
    """Keep a recovery cycle active until a final-answer adequacy review closes it."""

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
        recovery_cycle_active = False
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
            recovery_cycle_active = True
            _debug_recovery_exploration(recovery, recovery_history)

        delegate_system = system
        delegate_history = tool_history
        if recovery_cycle_active:
            delegate_system = f"{system}\n\n{_RECOVERY_EXPLORATION_INSTRUCTION}"
            delegate_history = [
                *tool_history,
                {
                    "tool": "tool_result_adequacy_guard",
                    "arguments": {},
                    "result": {
                        "ok": True,
                        "status": "evidence_recovery_cycle_active",
                        "message": _RECOVERY_EXPLORATION_INSTRUCTION,
                        "recovery_attempt": recovery.cycles_started,
                        "missing_aspects": list(recovery.missing_aspects),
                    },
                },
            ]

        delegate_started = perf_counter()
        try:
            turn = await self._delegate.next_turn(
                system=delegate_system,
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=delegate_history,
            )
        finally:
            log_timing(
                "normal_agent",
                perf_counter() - delegate_started,
                recovery_attempt=recovery.cycles_started or None,
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

        review_started = perf_counter()
        adequacy_result, grounding_result = await asyncio.gather(
            review_relaxed_tool_result_adequacy(
                system=f"{system}\n\n{_ADEQUACY_SCOPE_LOCK_INSTRUCTION}",
                user_message=user_message,
                model=model,
                requirements=requirements,
                tool_history=tool_history,
            ),
            review_final_grounding(
                system=system,
                user_message=user_message,
                proposed_response=turn.final_answer,
                model=model,
                tool_history=tool_history,
            ),
            return_exceptions=True,
        )
        log_timing("final_review_parallel_wall", perf_counter() - review_started)

        if isinstance(adequacy_result, BaseException):
            raise adequacy_result
        adequacy = adequacy_result
        _debug_adequacy(adequacy)

        if adequacy.adequate:
            if isinstance(grounding_result, BaseException):
                raise grounding_result
            store_precomputed_grounding_review(
                proposed_response=turn.final_answer,
                review=grounding_result,
            )
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


def _debug_recovery_exploration(
    recovery: RecoveryState,
    recovery_history: list[dict[str, Any]],
) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    print(
        "[MK4 recovery] "
        f"attempt={recovery.cycles_started}/3 exploration_active=true "
        f"successful_events_since_cycle_start={_successful_event_count(recovery_history)} "
        f"missing={json.dumps(list(recovery.missing_aspects), ensure_ascii=False)}",
        file=sys.stderr,
        flush=True,
    )


def _successful_event_count(tool_history: list[dict[str, Any]]) -> int:
    count = 0
    for event in tool_history:
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("ok") is False:
            continue
        if "returncode" in result and result.get("returncode") not in {None, 0}:
            continue
        if event.get("tool") in {
            "execution_guard",
            "evidence_grounding_guard",
            "tool_requirement_guard",
            "tool_result_adequacy_guard",
            "autonomy_guard",
            "file_text_activation",
        }:
            continue
        count += 1
    return count
