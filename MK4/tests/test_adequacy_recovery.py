from __future__ import annotations

import json
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
        self.calls.append({
            "system": system,
            "tool_history": list(tool_history),
        })
        return self.turns.pop(0)


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} test tool",
        input_schema={"type": "object", "properties": {}},
    )


def _initial_requirements() -> FrozenToolRequirements:
    return FrozenToolRequirements(
        evaluations=(ToolEvaluation(tool="web_research", required=True),),
    )


def _recovery_requirements() -> FrozenToolRequirements:
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
async def test_recovery_planner_only_selects_tools_and_requires_at_least_one(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["system"] = system
        captured["payload"] = json.loads(user)
        captured["schema"] = response_format
        return json.dumps({
            "tool_requirements": {
                "latest_search": False,
                "web_research": True,
            }
        })

    monkeypatch.setattr(adequacy_recovery, "ollama_chat", fake_chat)
    plan = await adequacy_recovery.plan_recovery_tool_requirements(
        user_message="한국에서 법적 문제를 최소화할 서바이벌 나이프 3개 추천해줘",
        missing_aspects=("구체적인 제품 3종과 법적 기준의 근거",),
        successful_tool_results=[_event("initial")],
        model=None,
        tool_definitions=[_definition("latest_search"), _definition("web_research")],
        recovery_attempt=1,
    )

    assert plan.required_tools == ("web_research",)
    assert captured["payload"]["recovery_attempt"] == 1
    assert captured["payload"]["max_recovery_attempts"] == 3
    assert "missing_aspects" in captured["payload"]
    assert "tool_catalog" in captured["payload"]
    assert "queries" not in captured["payload"]
    assert "arguments" not in captured["payload"]
    assert "do not write tool arguments or search queries" in captured["system"].lower()


@pytest.mark.asyncio
async def test_recovery_planner_rejects_all_false_plan(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({"tool_requirements": {"web_research": False}})

    monkeypatch.setattr(adequacy_recovery, "ollama_chat", fake_chat)
    with pytest.raises(ToolRequirementPlanError, match="at least one"):
        await adequacy_recovery.plan_recovery_tool_requirements(
            user_message="추가 근거가 필요한 요청",
            missing_aspects=("추가 근거",),
            successful_tool_results=[],
            model=None,
            tool_definitions=[_definition("web_research")],
            recovery_attempt=1,
        )


@pytest.mark.asyncio
async def test_inadequate_evidence_uses_recovery_planner_then_normal_agent_builds_tool_call(monkeypatch) -> None:
    adequacy_answers = iter([
        ToolResultAdequacy(adequate=False, missing_aspects=("제품 3종 추가 근거",)),
        ToolResultAdequacy(adequate=True, missing_aspects=()),
    ])

    async def fake_adequacy(**kwargs):
        return next(adequacy_answers)

    async def fake_recovery_plan(**kwargs):
        assert kwargs["recovery_attempt"] == 1
        assert kwargs["missing_aspects"] == ("제품 3종 추가 근거",)
        return _recovery_requirements()

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    monkeypatch.setattr(adequacy_recovery, "plan_recovery_tool_requirements", fake_recovery_plan)

    tool_call = ToolCall(
        tool="web_research",
        arguments={"objective": "합법 범위 부시크래프트 나이프 제품 3종", "language": "ko"},
    )
    delegate = SequenceChatModel([
        ModelTurn(final_answer="첫 근거로 답하려는 초안"),
        ModelTurn(tool_calls=[tool_call]),
        ModelTurn(final_answer="추가 근거까지 반영한 답변"),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate, max_recovery_cycles=3)

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    try:
        freeze_tool_requirements(_initial_requirements())
        initial_history = [_event("initial")]
        first = await guarded.next_turn(
            system="system",
            user_message="한국에서 법적 문제를 최소화할 서바이벌 나이프 3개 추천해줘",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=initial_history,
        )
        assert first.tool_calls == [tool_call]
        assert get_recovery_state().cycles_started == 1
        assert delegate.calls[1]["tool_history"][-1]["result"]["recovery_missing_tools"] == ["web_research"]

        second = await guarded.next_turn(
            system="system",
            user_message="한국에서 법적 문제를 최소화할 서바이벌 나이프 3개 추천해줘",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=[*initial_history, _event("recovery-1")],
        )
        assert second.final_answer == "추가 근거까지 반영한 답변"
        assert get_recovery_state().cycles_started == 1
        assert get_recovery_state().requirements is None
    finally:
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)


@pytest.mark.asyncio
async def test_old_success_does_not_satisfy_new_recovery_requirement(monkeypatch) -> None:
    async def fake_adequacy(**kwargs):
        return ToolResultAdequacy(adequate=False, missing_aspects=("새 근거",))

    async def fake_recovery_plan(**kwargs):
        return _recovery_requirements()

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    monkeypatch.setattr(adequacy_recovery, "plan_recovery_tool_requirements", fake_recovery_plan)

    tool_call = ToolCall(tool="web_research", arguments={"objective": "새 검색", "language": "ko"})
    delegate = SequenceChatModel([
        ModelTurn(final_answer="초안"),
        ModelTurn(tool_calls=[tool_call]),
        ModelTurn(tool_calls=[tool_call]),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate, max_recovery_cycles=3)

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    try:
        freeze_tool_requirements(_initial_requirements())
        history = [_event("initial")]
        first = await guarded.next_turn(
            system="system",
            user_message="추가 근거가 필요한 요청",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=history,
        )
        assert first.tool_calls == [tool_call]

        second = await guarded.next_turn(
            system="system",
            user_message="추가 근거가 필요한 요청",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=history,
        )
        assert second.tool_calls == [tool_call]
        assert delegate.calls[2]["tool_history"][-1]["result"]["recovery_missing_tools"] == ["web_research"]
    finally:
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)


@pytest.mark.asyncio
async def test_recovery_is_bounded_to_three_adequacy_cycles(monkeypatch) -> None:
    async def fake_adequacy(**kwargs):
        return ToolResultAdequacy(adequate=False, missing_aspects=("아직 부족",))

    recovery_attempts: list[int] = []

    async def fake_recovery_plan(**kwargs):
        recovery_attempts.append(kwargs["recovery_attempt"])
        return _recovery_requirements()

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    monkeypatch.setattr(adequacy_recovery, "plan_recovery_tool_requirements", fake_recovery_plan)

    delegate = SequenceChatModel([
        ModelTurn(final_answer="draft-1"),
        ModelTurn(tool_calls=[ToolCall(tool="web_research", arguments={"objective": "r1"})]),
        ModelTurn(final_answer="draft-2"),
        ModelTurn(tool_calls=[ToolCall(tool="web_research", arguments={"objective": "r2"})]),
        ModelTurn(final_answer="draft-3"),
        ModelTurn(tool_calls=[ToolCall(tool="web_research", arguments={"objective": "r3"})]),
        ModelTurn(final_answer="draft-after-3"),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate, max_recovery_cycles=3)

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    try:
        freeze_tool_requirements(_initial_requirements())
        history = [_event("initial")]

        first = await guarded.next_turn(
            system="system", user_message="request", model=None, memory_summary=[],
            tool_definitions=[_definition("web_research")], tool_history=history,
        )
        assert first.tool_calls
        history.append(_event("recovery-1"))

        second = await guarded.next_turn(
            system="system", user_message="request", model=None, memory_summary=[],
            tool_definitions=[_definition("web_research")], tool_history=history,
        )
        assert second.tool_calls
        history.append(_event("recovery-2"))

        third = await guarded.next_turn(
            system="system", user_message="request", model=None, memory_summary=[],
            tool_definitions=[_definition("web_research")], tool_history=history,
        )
        assert third.tool_calls
        history.append(_event("recovery-3"))

        fourth = await guarded.next_turn(
            system="system", user_message="request", model=None, memory_summary=[],
            tool_definitions=[_definition("web_research")], tool_history=history,
        )
        assert fourth.final_answer_kind == "blocked"
        assert "3회" in fourth.final_answer
        assert recovery_attempts == [1, 2, 3]
        assert get_recovery_state().cycles_started == 3
    finally:
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)


@pytest.mark.asyncio
async def test_selected_recovery_tool_still_fails_visibly_if_normal_agent_never_executes_it(monkeypatch) -> None:
    async def fake_adequacy(**kwargs):
        return ToolResultAdequacy(adequate=False, missing_aspects=("추가 근거",))

    async def fake_recovery_plan(**kwargs):
        return _recovery_requirements()

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    monkeypatch.setattr(adequacy_recovery, "plan_recovery_tool_requirements", fake_recovery_plan)

    delegate = SequenceChatModel([
        ModelTurn(final_answer="초안"),
        ModelTurn(final_answer="툴 없이 답변"),
        ModelTurn(final_answer="그래도 툴 없이 답변"),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate, max_recovery_cycles=3)

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    try:
        freeze_tool_requirements(_initial_requirements())
        turn = await guarded.next_turn(
            system="system",
            user_message="추가 근거가 필요한 요청",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=[_event("initial")],
        )
        assert turn.final_answer_kind == "blocked"
        assert "필요한 도구가 선택되었지만 실제 실행" in turn.final_answer
        assert get_recovery_state().cycles_started == 1
    finally:
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)
