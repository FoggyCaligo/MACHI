from __future__ import annotations

import asyncio
from typing import Any

import pytest

from MK4.tools import adequacy_recovery_window
from MK4.tools.adequacy_recovery import (
    RecoveryState,
    _set_recovery_state,
    get_recovery_state,
    reset_recovery_scope,
    start_recovery_scope,
)
from MK4.tools.adequacy_recovery_window import RecoveryExplorationWindowChatModel
from MK4.tools.grounding_tools import (
    GroundingReview,
    reset_grounding_review_scope,
    start_grounding_review_scope,
)
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_requirements import (
    FrozenToolRequirements,
    ToolEvaluation,
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


def _definition(name: str = "web_research") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} test tool",
        input_schema={"type": "object", "properties": {}},
    )


def _requirements() -> FrozenToolRequirements:
    return FrozenToolRequirements(
        evaluations=(ToolEvaluation(tool="web_research", required=True),),
    )


def _event(label: str) -> dict[str, Any]:
    return {
        "tool": "web_research",
        "arguments": {"objective": label, "language": "en"},
        "result": {"ok": True, "results": [{"title": label}]},
    }


def _install_successful_reviewers(monkeypatch, adequacy_counter: list[int]) -> None:
    async def fake_adequacy(**kwargs):
        adequacy_counter[0] += 1
        return ToolResultAdequacy(adequate=True, missing_aspects=())

    async def fake_grounding(**kwargs):
        return GroundingReview(grounded=True, missing_aspects=())

    monkeypatch.setattr(
        adequacy_recovery_window,
        "review_relaxed_tool_result_adequacy",
        fake_adequacy,
    )
    monkeypatch.setattr(adequacy_recovery_window, "review_final_grounding", fake_grounding)


@pytest.mark.asyncio
async def test_satisfied_recovery_requirement_keeps_cycle_open_for_more_tool_calls(monkeypatch) -> None:
    adequacy_calls = [0]
    _install_successful_reviewers(monkeypatch, adequacy_calls)

    second_search = ToolCall(
        tool="web_research",
        arguments={"objective": "specific full tang models", "language": "en"},
    )
    delegate = SequenceChatModel([
        ModelTurn(tool_calls=[second_search]),
        ModelTurn(final_answer="evidence is now sufficient"),
    ])
    guarded = RecoveryExplorationWindowChatModel(delegate, max_recovery_cycles=3)

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    grounding_token = start_grounding_review_scope()
    try:
        freeze_tool_requirements(_requirements())
        initial = _event("initial comparison")
        first_recovery = _event("first recovery search")
        _set_recovery_state(
            RecoveryState(
                cycles_started=1,
                requirements=_requirements(),
                baseline_history_len=1,
                missing_aspects=("specific model recommendations",),
                reviewed_evidence_version=1,
            )
        )

        first = await guarded.next_turn(
            system="system",
            user_message="recommend specific bushcraft knife models",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition()],
            tool_history=[initial, first_recovery],
        )

        assert first.tool_calls == [second_search]
        assert adequacy_calls[0] == 0
        active = get_recovery_state()
        assert active.cycles_started == 1
        assert active.requirements is not None
        assert active.missing_aspects == ("specific model recommendations",)
        assert "recovery cycle remains active" in delegate.calls[0]["system"].lower()
        assert delegate.calls[0]["tool_history"][-1]["result"]["status"] == "evidence_recovery_cycle_active"

        second_recovery = _event("second recovery search")
        second = await guarded.next_turn(
            system="system",
            user_message="recommend specific bushcraft knife models",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition()],
            tool_history=[initial, first_recovery, second_recovery],
        )

        assert second.final_answer == "evidence is now sufficient"
        assert adequacy_calls[0] == 1
        closed = get_recovery_state()
        assert closed.cycles_started == 1
        assert closed.requirements is None
        assert closed.missing_aspects == ()
    finally:
        reset_grounding_review_scope(grounding_token)
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_cycle_do_not_consume_additional_recovery_cycles(monkeypatch) -> None:
    adequacy_calls = [0]
    _install_successful_reviewers(monkeypatch, adequacy_calls)

    third_search = ToolCall(
        tool="web_research",
        arguments={"objective": "specific folding models", "language": "en"},
    )
    fourth_search = ToolCall(
        tool="web_research",
        arguments={"objective": "compare recommended models", "language": "en"},
    )
    delegate = SequenceChatModel([
        ModelTurn(tool_calls=[third_search]),
        ModelTurn(tool_calls=[fourth_search]),
        ModelTurn(final_answer="final after several searches"),
    ])
    guarded = RecoveryExplorationWindowChatModel(delegate, max_recovery_cycles=3)

    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    grounding_token = start_grounding_review_scope()
    try:
        freeze_tool_requirements(_requirements())
        initial = _event("initial")
        recovery_one = _event("recovery one")
        _set_recovery_state(
            RecoveryState(
                cycles_started=1,
                requirements=_requirements(),
                baseline_history_len=1,
                missing_aspects=("specific fixed and folding models",),
                reviewed_evidence_version=1,
            )
        )

        history = [initial, recovery_one]
        turn_one = await guarded.next_turn(
            system="system", user_message="request", model=None, memory_summary=[],
            tool_definitions=[_definition()], tool_history=history,
        )
        assert turn_one.tool_calls == [third_search]
        assert get_recovery_state().cycles_started == 1

        history.append(_event("recovery two"))
        turn_two = await guarded.next_turn(
            system="system", user_message="request", model=None, memory_summary=[],
            tool_definitions=[_definition()], tool_history=history,
        )
        assert turn_two.tool_calls == [fourth_search]
        assert get_recovery_state().cycles_started == 1
        assert adequacy_calls[0] == 0

        history.append(_event("recovery three"))
        final = await guarded.next_turn(
            system="system", user_message="request", model=None, memory_summary=[],
            tool_definitions=[_definition()], tool_history=history,
        )
        assert final.final_answer == "final after several searches"
        assert adequacy_calls[0] == 1
        assert get_recovery_state().cycles_started == 1
    finally:
        reset_grounding_review_scope(grounding_token)
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)


@pytest.mark.asyncio
async def test_final_only_starts_adequacy_and_grounding_concurrently(monkeypatch) -> None:
    adequacy_started = asyncio.Event()
    grounding_started = asyncio.Event()

    async def fake_adequacy(**kwargs):
        adequacy_started.set()
        await grounding_started.wait()
        return ToolResultAdequacy(adequate=True, missing_aspects=())

    async def fake_grounding(**kwargs):
        grounding_started.set()
        await adequacy_started.wait()
        return GroundingReview(grounded=True, missing_aspects=())

    monkeypatch.setattr(
        adequacy_recovery_window,
        "review_relaxed_tool_result_adequacy",
        fake_adequacy,
    )
    monkeypatch.setattr(adequacy_recovery_window, "review_final_grounding", fake_grounding)

    guarded = RecoveryExplorationWindowChatModel(
        SequenceChatModel([ModelTurn(final_answer="final draft")])
    )
    requirement_token = start_tool_requirement_scope()
    recovery_token = start_recovery_scope()
    grounding_token = start_grounding_review_scope()
    try:
        freeze_tool_requirements(_requirements())
        result = await asyncio.wait_for(
            guarded.next_turn(
                system="system",
                user_message="request",
                model=None,
                memory_summary=[],
                tool_definitions=[_definition()],
                tool_history=[_event("evidence")],
            ),
            timeout=1,
        )
        assert result.final_answer == "final draft"
        assert adequacy_started.is_set()
        assert grounding_started.is_set()
    finally:
        reset_grounding_review_scope(grounding_token)
        reset_recovery_scope(recovery_token)
        reset_tool_requirement_scope(requirement_token)
