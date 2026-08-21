from __future__ import annotations

from typing import Any

import pytest

from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolCall, ToolDefinition
from MK4.tools.work_planning import WorkPlanningChatModel


class SequenceChatModel:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self._turns = list(turns)
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
            "user_message": user_message,
            "tool_history": tool_history,
        })
        return self._turns.pop(0)


def _defs(*names: str) -> list[ToolDefinition]:
    return [
        ToolDefinition(name=name, description=name, input_schema={"type": "object"})
        for name in names
    ]


def _manual_event(tool: str) -> dict[str, Any]:
    return {
        "tool": "tool_manual",
        "arguments": {"tool": tool},
        "result": {"ok": True, "tool": tool, "description": tool, "input_schema": {}},
    }


def _plan_event(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tool": "work_plan",
        "arguments": {},
        "result": {
            "ok": True,
            "goal": "complete the request",
            "steps": steps,
        },
    }


@pytest.mark.asyncio
async def test_work_plan_manual_is_framework_prerequisite() -> None:
    delegate = SequenceChatModel([])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="question",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete"),
        tool_history=[],
    )

    assert turn.tool_calls == [ToolCall(tool="tool_manual", arguments={"tool": "work_plan"})]
    assert delegate.calls == []


@pytest.mark.asyncio
async def test_model_creates_plan_after_work_plan_manual() -> None:
    plan_call = ToolCall(
        tool="work_plan",
        arguments={
            "goal": "answer",
            "steps": [{
                "step_id": "s1",
                "claim": "derive the answer",
                "action_type": "reasoning",
                "tool": None,
                "depends_on": [],
            }],
        },
    )
    delegate = SequenceChatModel([ModelTurn(tool_calls=[plan_call])])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="question",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete"),
        tool_history=[_manual_event("work_plan")],
    )

    assert turn.tool_calls == [plan_call]
    assert "create a work_plan" in delegate.calls[0]["system"]


@pytest.mark.asyncio
async def test_reasoning_step_manual_is_loaded_before_model_execution() -> None:
    history = [
        _manual_event("work_plan"),
        _plan_event([{
            "step_id": "reason-1",
            "claim": "analyze the request",
            "action_type": "reasoning",
            "tool": None,
            "depends_on": [],
        }]),
    ]
    delegate = SequenceChatModel([])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="question",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete"),
        tool_history=history,
    )

    assert turn.tool_calls == [ToolCall(
        tool="tool_manual",
        arguments={"tool": "work_step_complete"},
    )]
    assert delegate.calls == []


@pytest.mark.asyncio
async def test_reasoning_step_requires_exact_step_completion_after_manual() -> None:
    history = [
        _manual_event("work_plan"),
        _plan_event([{
            "step_id": "reason-1",
            "claim": "analyze the request",
            "action_type": "reasoning",
            "tool": None,
            "depends_on": [],
        }]),
        _manual_event("work_step_complete"),
    ]
    expected = ToolCall(
        tool="work_step_complete",
        arguments={"step_id": "reason-1", "conclusion": "analysis complete"},
    )
    delegate = SequenceChatModel([ModelTurn(tool_calls=[expected])])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="question",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete"),
        tool_history=history,
    )

    assert turn.tool_calls == [expected]


@pytest.mark.asyncio
async def test_planned_tool_manual_is_loaded_before_tool_step() -> None:
    steps = [{
        "step_id": "find",
        "claim": "find the target file",
        "action_type": "tool",
        "tool": "file_search",
        "depends_on": [],
    }]
    history = [_manual_event("work_plan"), _plan_event(steps)]
    delegate = SequenceChatModel([])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="edit the html",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete", "file_search"),
        tool_history=history,
    )

    assert turn.tool_calls == [ToolCall(tool="tool_manual", arguments={"tool": "file_search"})]
    assert delegate.calls == []


@pytest.mark.asyncio
async def test_tool_steps_must_follow_declared_order_after_manuals() -> None:
    steps = [
        {
            "step_id": "find",
            "claim": "find the target file",
            "action_type": "tool",
            "tool": "file_search",
            "depends_on": [],
        },
        {
            "step_id": "read",
            "claim": "inspect the target section",
            "action_type": "tool",
            "tool": "file_read",
            "depends_on": ["find"],
        },
    ]
    history = [
        _manual_event("work_plan"),
        _plan_event(steps),
        _manual_event("file_search"),
    ]
    wrong = ModelTurn(tool_calls=[ToolCall(tool="file_read", arguments={"path": "x"})])
    corrected = ModelTurn(tool_calls=[ToolCall(tool="file_search", arguments={"pattern": "*.html"})])
    delegate = SequenceChatModel([wrong, corrected])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="edit the html",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete", "file_search", "file_read"),
        tool_history=history,
    )

    assert [call.tool for call in turn.tool_calls] == ["file_search"]
    assert delegate.calls[1]["tool_history"][-1]["tool"] == "work_plan_guard"


@pytest.mark.asyncio
async def test_next_tool_step_gets_its_manual_after_previous_success() -> None:
    steps = [
        {
            "step_id": "find",
            "claim": "find the file",
            "action_type": "tool",
            "tool": "file_search",
            "depends_on": [],
        },
        {
            "step_id": "read",
            "claim": "read the file",
            "action_type": "tool",
            "tool": "file_read",
            "depends_on": ["find"],
        },
    ]
    history = [
        _manual_event("work_plan"),
        _plan_event(steps),
        _manual_event("file_search"),
        {
            "tool": "file_search",
            "arguments": {"pattern": "*.html"},
            "result": {"ok": True, "files": ["index.html"]},
        },
    ]
    delegate = SequenceChatModel([])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="edit the html",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete", "file_search", "file_read"),
        tool_history=history,
    )

    assert turn.tool_calls == [ToolCall(tool="tool_manual", arguments={"tool": "file_read"})]


@pytest.mark.asyncio
async def test_final_answer_is_allowed_only_after_all_steps_complete() -> None:
    steps = [{
        "step_id": "reason-1",
        "claim": "derive the answer",
        "action_type": "reasoning",
        "tool": None,
        "depends_on": [],
    }]
    history = [
        _manual_event("work_plan"),
        _plan_event(steps),
        _manual_event("work_step_complete"),
        {
            "tool": "work_step_complete",
            "arguments": {"step_id": "reason-1", "conclusion": "done"},
            "result": {"ok": True, "step_id": "reason-1", "conclusion": "done"},
        },
    ]
    delegate = SequenceChatModel([ModelTurn(final_answer="complete answer")])
    model = WorkPlanningChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="question",
        model=None,
        memory_summary=[],
        tool_definitions=_defs("tool_manual", "work_plan", "work_step_complete"),
        tool_history=history,
    )

    assert turn.final_answer == "complete answer"
