from __future__ import annotations

from typing import Any

import pytest

from MK4.tools import adequacy_recovery
from MK4.tools.adequacy_recovery import (
    RecoveringToolRequirementGuardChatModel,
    get_recovery_state,
    reset_recovery_scope,
    start_recovery_scope,
)
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_requirements import (
    FrozenToolRequirements,
    ToolEvaluation,
    ToolRequirementPlanError,
    ToolResultAdequacy,
    freeze_tool_requirements,
    reset_tool_requirement_scope,
    start_tool_requirement_scope,
)
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


class SequenceChatModel:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append({"system": system, "tool_history": list(tool_history)})
        return self.turns.pop(0)


def _definition() -> ToolDefinition:
    return ToolDefinition(
        name="web_research",
        description="deep web research",
        input_schema={"type": "object", "properties": {}},
    )


def _requirements() -> FrozenToolRequirements:
    return FrozenToolRequirements(
        evaluations=(ToolEvaluation(tool="web_research", required=True),),
    )


def _event(label: str) -> dict[str, Any]:
    return {
        "tool": "web_research",
        "arguments": {"objective": label, "language": "ko"},
        "result": {"ok": True, "results": [{"title": label}]},
    }


@pytest.mark.asyncio
async def test_adequacy_review_receives_scope_lock_contract(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_adequacy(**kwargs):
        captured["system"] = kwargs["system"]
        return ToolResultAdequacy(adequate=True, missing_aspects=())

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    delegate = SequenceChatModel([ModelTurn(final_answer="제품 3개를 추천합니다.")])
    guarded = RecoveringToolRequirementGuardChatModel(delegate)

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    try:
        freeze_tool_requirements(_requirements())
        turn = await guarded.next_turn(
            system="system",
            user_message="법적 조건을 고려한 부시크래프트 나이프 3개 추천",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition()],
            tool_history=[_event("initial")],
        )
    finally:
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)

    assert turn.final_answer == "제품 3개를 추천합니다."
    lowered = captured["system"].lower()
    assert "scope-locked" in lowered
    assert "do not replace the requested target" in lowered
    assert "professional consultation" in lowered
    assert "alternative product/category" in lowered


@pytest.mark.asyncio
async def test_same_evidence_reuses_inadequate_review_after_recovery_planner_failure(monkeypatch) -> None:
    adequacy_calls = 0
    planner_calls = 0

    async def fake_adequacy(**kwargs):
        nonlocal adequacy_calls
        adequacy_calls += 1
        return ToolResultAdequacy(
            adequate=False,
            missing_aspects=("요청한 나이프 3종의 구체 제품 사양과 법적 기준 근거",),
        )

    async def fake_recovery_plan(**kwargs):
        nonlocal planner_calls
        planner_calls += 1
        assert kwargs["recovery_attempt"] == 1
        if planner_calls == 1:
            raise ToolRequirementPlanError("simulated recovery planner parse failure")
        return _requirements()

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    monkeypatch.setattr(adequacy_recovery, "plan_recovery_tool_requirements", fake_recovery_plan)

    recovery_call = ToolCall(
        tool="web_research",
        arguments={"objective": "부시크래프트 나이프 3종 제품 사양과 국내 도검 기준", "language": "ko"},
    )
    delegate = SequenceChatModel([
        ModelTurn(final_answer="첫 초안"),
        ModelTurn(final_answer="같은 근거로 다시 만든 초안"),
        ModelTurn(tool_calls=[recovery_call]),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate)
    history = [_event("initial")]

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    try:
        freeze_tool_requirements(_requirements())
        with pytest.raises(ToolRequirementPlanError, match="simulated"):
            await guarded.next_turn(
                system="system",
                user_message="법적 조건을 고려한 부시크래프트 나이프 3개 추천",
                model=None,
                memory_summary=[],
                tool_definitions=[_definition()],
                tool_history=history,
            )

        pending = get_recovery_state()
        assert pending.cycles_started == 0
        assert pending.requirements is None
        assert pending.missing_aspects == ("요청한 나이프 3종의 구체 제품 사양과 법적 기준 근거",)
        assert pending.reviewed_evidence_version == 1

        second = await guarded.next_turn(
            system="system",
            user_message="법적 조건을 고려한 부시크래프트 나이프 3개 추천",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition()],
            tool_history=history,
        )
    finally:
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)

    assert second.tool_calls == [recovery_call]
    assert adequacy_calls == 1
    assert planner_calls == 2
    assert get_recovery_state().cycles_started == 0


@pytest.mark.asyncio
async def test_new_successful_evidence_allows_fresh_adequacy_review(monkeypatch) -> None:
    adequacy_answers = iter([
        ToolResultAdequacy(adequate=False, missing_aspects=("제품 3종 근거",)),
        ToolResultAdequacy(adequate=True, missing_aspects=()),
    ])
    adequacy_calls = 0

    async def fake_adequacy(**kwargs):
        nonlocal adequacy_calls
        adequacy_calls += 1
        return next(adequacy_answers)

    async def fake_recovery_plan(**kwargs):
        return _requirements()

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    monkeypatch.setattr(adequacy_recovery, "plan_recovery_tool_requirements", fake_recovery_plan)

    recovery_call = ToolCall(
        tool="web_research",
        arguments={"objective": "제품 3종 추가 조사", "language": "ko"},
    )
    delegate = SequenceChatModel([
        ModelTurn(final_answer="첫 초안"),
        ModelTurn(tool_calls=[recovery_call]),
        ModelTurn(final_answer="새 근거를 반영한 최종 답변"),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate)
    initial_history = [_event("initial")]

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    try:
        freeze_tool_requirements(_requirements())
        first = await guarded.next_turn(
            system="system",
            user_message="나이프 3개 추천",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition()],
            tool_history=initial_history,
        )
        assert first.tool_calls == [recovery_call]

        second = await guarded.next_turn(
            system="system",
            user_message="나이프 3개 추천",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition()],
            tool_history=[*initial_history, _event("recovery")],
        )
    finally:
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)

    assert second.final_answer == "새 근거를 반영한 최종 답변"
    assert adequacy_calls == 2
