from __future__ import annotations

import json
from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolCall, ToolDefinition


_PLAN_REQUIRED_INSTRUCTION = """
Before doing any work for the current user request, create a work_plan.
The plan is internal execution structure, not the user-visible answer.
Split the request into the smallest useful ordered steps. Each step establishes one claim or result needed for the final answer.
Use action_type='tool' for a concrete tool execution and action_type='reasoning' for internal analysis.
Do not perform later steps early. Do not return a final answer until every planned step is complete.
""".strip()

_STEP_INSTRUCTION = """
Follow the current work_plan exactly in order.
Perform only the current pending step. Do not skip ahead, combine later work, or return the final answer yet.
For a tool step, call the exact planned tool. A tool_manual prerequisite may be called as needed.
For a reasoning step, complete the reasoning and call work_step_complete with the exact step_id and concise conclusion.
""".strip()

_PLAN_COMPLETE_INSTRUCTION = """
The current work_plan is complete. Synthesize the complete user-visible answer from the completed steps and collected evidence.
If additional work is actually required, create a new work_plan before calling any other tool.
""".strip()


class WorkPlanningChatModel:
    """Require every request to be planned, then executed one structural step at a time."""

    def __init__(self, delegate: ChatModel, *, max_retries: int = 1) -> None:
        self._delegate = delegate
        self._max_retries = max(0, max_retries)

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
        plan_event = _latest_successful_plan_event(tool_history)
        if plan_event is None:
            return await self._require_plan(
                system=system,
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=tool_history,
            )

        plan = plan_event.get("result") if isinstance(plan_event.get("result"), dict) else {}
        pending = _next_pending_step(plan=plan, tool_history=tool_history, plan_event=plan_event)
        if pending is not None:
            return await self._require_current_step(
                pending=pending,
                system=system,
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=tool_history,
            )

        return await self._require_final_or_replan(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )

    async def _require_plan(self, **kwargs: Any) -> ModelTurn:
        turn = await self._delegate.next_turn(
            system=f"{kwargs['system']}\n{_PLAN_REQUIRED_INSTRUCTION}",
            user_message=kwargs["user_message"],
            model=kwargs["model"],
            memory_summary=kwargs["memory_summary"],
            tool_definitions=kwargs["tool_definitions"],
            tool_history=kwargs["tool_history"],
        )
        if _is_plan_turn(turn):
            return turn
        return await self._retry_or_block(
            reason="work_plan_required",
            instruction=_PLAN_REQUIRED_INSTRUCTION,
            rejected=turn,
            **kwargs,
        )

    async def _require_current_step(self, *, pending: dict[str, Any], **kwargs: Any) -> ModelTurn:
        step_instruction = (
            _STEP_INSTRUCTION
            + "\nCurrent step:\n"
            + json.dumps(pending, ensure_ascii=False, sort_keys=True)
        )
        turn = await self._delegate.next_turn(
            system=f"{kwargs['system']}\n{step_instruction}",
            user_message=kwargs["user_message"],
            model=kwargs["model"],
            memory_summary=kwargs["memory_summary"],
            tool_definitions=kwargs["tool_definitions"],
            tool_history=kwargs["tool_history"],
        )
        if _matches_pending_step(turn, pending):
            return turn
        return await self._retry_or_block(
            reason="work_plan_step_mismatch",
            instruction=step_instruction,
            rejected=turn,
            pending=pending,
            **kwargs,
        )

    async def _require_final_or_replan(self, **kwargs: Any) -> ModelTurn:
        turn = await self._delegate.next_turn(
            system=f"{kwargs['system']}\n{_PLAN_COMPLETE_INSTRUCTION}",
            user_message=kwargs["user_message"],
            model=kwargs["model"],
            memory_summary=kwargs["memory_summary"],
            tool_definitions=kwargs["tool_definitions"],
            tool_history=kwargs["tool_history"],
        )
        if turn.final_answer and not turn.tool_calls:
            return turn
        if _is_plan_turn(turn):
            return turn
        return await self._retry_or_block(
            reason="work_plan_complete_requires_final_or_replan",
            instruction=_PLAN_COMPLETE_INSTRUCTION,
            rejected=turn,
            **kwargs,
        )

    async def _retry_or_block(
        self,
        *,
        reason: str,
        instruction: str,
        rejected: ModelTurn,
        pending: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ModelTurn:
        if self._max_retries <= 0:
            return _blocked_turn(reason)
        retry_history = [
            *kwargs["tool_history"],
            {
                "tool": "work_plan_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": reason,
                    "message": instruction,
                    "pending_step": pending,
                    "rejected_final_answer": rejected.final_answer,
                    "rejected_tools": [call.tool for call in rejected.tool_calls],
                },
            },
        ]
        retried = await self._delegate.next_turn(
            system=f"{kwargs['system']}\n{instruction}",
            user_message=kwargs["user_message"],
            model=kwargs["model"],
            memory_summary=kwargs["memory_summary"],
            tool_definitions=kwargs["tool_definitions"],
            tool_history=retry_history,
        )
        if reason == "work_plan_required" and _is_plan_turn(retried):
            return retried
        if reason == "work_plan_step_mismatch" and pending is not None and _matches_pending_step(retried, pending):
            return retried
        if reason == "work_plan_complete_requires_final_or_replan":
            if (retried.final_answer and not retried.tool_calls) or _is_plan_turn(retried):
                return retried
        return _blocked_turn(reason)


def _latest_successful_plan_event(tool_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(tool_history):
        result = event.get("result")
        if event.get("tool") == "work_plan" and isinstance(result, dict) and result.get("ok") is True:
            return event
    return None


def _next_pending_step(
    *,
    plan: dict[str, Any],
    tool_history: list[dict[str, Any]],
    plan_event: dict[str, Any],
) -> dict[str, Any] | None:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return None
    try:
        start_index = tool_history.index(plan_event) + 1
    except ValueError:
        start_index = 0
    cursor = start_index
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        match_index = _completion_event_index(raw_step, tool_history, cursor)
        if match_index is None:
            return dict(raw_step)
        cursor = match_index + 1
    return None


def _completion_event_index(
    step: dict[str, Any],
    tool_history: list[dict[str, Any]],
    start_index: int,
) -> int | None:
    action_type = str(step.get("action_type") or "")
    step_id = str(step.get("step_id") or "")
    planned_tool = str(step.get("tool") or "")
    for index in range(start_index, len(tool_history)):
        event = tool_history[index]
        result = event.get("result")
        if not _event_succeeded(result):
            continue
        if action_type == "reasoning":
            if (
                event.get("tool") == "work_step_complete"
                and isinstance(result, dict)
                and str(result.get("step_id") or "") == step_id
            ):
                return index
        elif action_type == "tool" and event.get("tool") == planned_tool:
            return index
    return None


def _event_succeeded(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    if "ok" in result:
        return result.get("ok") is True
    if "returncode" in result:
        return result.get("returncode") == 0
    return not result.get("error")


def _is_plan_turn(turn: ModelTurn) -> bool:
    if turn.final_answer:
        return False
    substantive = [call for call in turn.tool_calls if call.tool != "tool_manual"]
    return bool(substantive) and all(call.tool == "work_plan" for call in substantive)


def _matches_pending_step(turn: ModelTurn, pending: dict[str, Any]) -> bool:
    if turn.final_answer:
        return False
    substantive = [call for call in turn.tool_calls if call.tool != "tool_manual"]
    if not substantive:
        return False
    action_type = str(pending.get("action_type") or "")
    if action_type == "reasoning":
        if len(substantive) != 1 or substantive[0].tool != "work_step_complete":
            return False
        return str(substantive[0].arguments.get("step_id") or "") == str(pending.get("step_id") or "")
    if action_type == "tool":
        planned_tool = str(pending.get("tool") or "")
        return all(call.tool == planned_tool for call in substantive)
    return False


def _blocked_turn(reason: str) -> ModelTurn:
    return ModelTurn(
        final_answer=f"작업 계획 계약을 충족하지 못해 실행을 중단했습니다: {reason}",
        final_answer_kind="blocked",
    )
