from __future__ import annotations

from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_requirements import (
    _ADEQUACY_RETRY_INSTRUCTION,
    _REQUIREMENT_RETRY_INSTRUCTION,
    _debug_adequacy,
    _debug_missing_requirements,
    _debug_requirement_plan,
    _successful_tool_result_payloads,
    freeze_tool_requirements,
    get_frozen_tool_requirements,
    missing_required_tools,
    plan_tool_requirements,
    review_tool_result_adequacy,
)
from .tool_runtime import ToolDefinition


_RECOVERY_OBLIGATION_INSTRUCTION = """
The previous evidence review found unresolved missing aspects, so this request still has an active evidence-recovery obligation.
A final answer cannot be released yet. Execute at least one exposed tool that can make progress on the listed missing aspects.
Choose the tool and query yourself from the exposed capabilities. Do not invent a tool, do not merely restate the missing information, and do not replace execution with advice to the user.
""".strip()


class RecoveringToolRequirementGuardChatModel:
    """Frozen tool guard with a structural action obligation after inadequate evidence."""

    def __init__(self, delegate: ChatModel, *, max_recovery_retries: int = 2) -> None:
        self._delegate = delegate
        self._max_recovery_retries = max(1, max_recovery_retries)

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

        recovery_history = [
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
                    "evidence_recovery_required": True,
                },
            },
        ]

        for attempt in range(self._max_recovery_retries):
            retry_instruction = (
                _ADEQUACY_RETRY_INSTRUCTION
                if attempt == 0
                else _RECOVERY_OBLIGATION_INSTRUCTION
            )
            retry = await self._delegate.next_turn(
                system=f"{system}\n\n{retry_instruction}",
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=recovery_history,
            )
            if retry.tool_calls or not retry.final_answer or retry.final_answer_kind == "blocked":
                return retry

            recovery_history = [
                *recovery_history,
                {
                    "tool": "tool_result_adequacy_guard",
                    "arguments": {},
                    "result": {
                        "ok": False,
                        "error": "evidence_recovery_obligation_unmet",
                        "message": _RECOVERY_OBLIGATION_INSTRUCTION,
                        "missing_aspects": list(adequacy.missing_aspects),
                        "evidence_recovery_required": True,
                        "rejected_response": retry.final_answer[:1000],
                    },
                },
            ]

        return ModelTurn(
            final_answer="추가 근거 확보가 필요한 상태에서 도구 실행이 이루어지지 않아 답변을 확정하지 않았습니다.",
            final_answer_kind="blocked",
        )
