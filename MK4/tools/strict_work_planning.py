from __future__ import annotations

import json
from typing import Any

from .llm_client import ChatModel, ModelOutputParseError, ModelRequestError, ModelTurn
from .required_tool_model import RequiredToolChatModel
from .work_planning import (
    WorkPlanningChatModel,
    _PLAN_REQUIRED_INSTRUCTION,
    _STEP_INSTRUCTION,
    _matches_pending_step,
    _required_tool_for_step,
)


class StrictWorkPlanningChatModel(WorkPlanningChatModel):
    """Enforce plan/step phases with required-tool-only model schemas.

    The model still authors the plan and each step's arguments. What it cannot do
    during those phases is choose a final answer or a different tool instead of
    the structurally required action.
    """

    def __init__(
        self,
        delegate: ChatModel,
        *,
        required_tool_model: RequiredToolChatModel,
    ) -> None:
        super().__init__(delegate, max_retries=0)
        self._required_tool_model = required_tool_model

    async def _require_plan(self, **kwargs: Any) -> ModelTurn:
        return await self._required_tool_model.next_required_tool(
            required_tool="work_plan",
            system=f"{kwargs['system']}\n{_PLAN_REQUIRED_INSTRUCTION}",
            user_message=kwargs["user_message"],
            model=kwargs["model"],
            memory_summary=kwargs["memory_summary"],
            tool_definitions=kwargs["tool_definitions"],
            tool_history=kwargs["tool_history"],
        )

    async def _require_current_step(self, *, pending: dict[str, Any], **kwargs: Any) -> ModelTurn:
        required_tool = _required_tool_for_step(pending)
        available = {definition.name for definition in kwargs["tool_definitions"]}
        if required_tool not in available:
            raise ModelRequestError(f"Planned tool is not model-visible: {required_tool}")

        step_instruction = (
            _STEP_INSTRUCTION
            + "\nCurrent step:\n"
            + json.dumps(pending, ensure_ascii=False, sort_keys=True)
        )
        turn = await self._required_tool_model.next_required_tool(
            required_tool=required_tool,
            system=f"{kwargs['system']}\n{step_instruction}",
            user_message=kwargs["user_message"],
            model=kwargs["model"],
            memory_summary=kwargs["memory_summary"],
            tool_definitions=kwargs["tool_definitions"],
            tool_history=kwargs["tool_history"],
        )
        if not _matches_pending_step(turn, pending):
            raise ModelOutputParseError(
                f"Required tool call did not complete current work-plan step: {pending.get('step_id')!r}"
            )
        return turn

    async def _require_final_or_replan(self, **kwargs: Any) -> ModelTurn:
        # Final synthesis is intentionally unconstrained: only after every planned
        # step has completed may the normal model return the single user-visible
        # answer or explicitly create a new plan for genuinely additional work.
        return await super()._require_final_or_replan(**kwargs)
