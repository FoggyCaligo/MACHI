from __future__ import annotations

from typing import Any

import pytest

from MK4.tools.autonomy_tools import AutonomyChatModel
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


class ScriptedChatModel:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def next_turn(self, **kwargs: Any) -> ModelTurn:
        self.calls.append(kwargs)
        return self.turns.pop(0)


def _tools(*names: str) -> list[ToolDefinition]:
    return [ToolDefinition(name=name, description=name, input_schema={}) for name in names]


@pytest.mark.asyncio
async def test_blocked_without_tool_failure_gets_structural_retry() -> None:
    delegate = ScriptedChatModel([
        ModelTurn(final_answer="I cannot access the PC.", final_answer_kind="blocked"),
        ModelTurn(tool_calls=[ToolCall(tool="terminal_command", arguments={"command": "echo ok"})]),
    ])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="do the system task",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("terminal_command"),
        tool_history=[],
    )

    assert turn.tool_calls == [ToolCall(tool="terminal_command", arguments={"command": "echo ok"})]
    assert len(delegate.calls) == 2
    retry_history = delegate.calls[1]["tool_history"]
    assert retry_history[-1]["tool"] == "autonomy_guard"
    assert retry_history[-1]["result"]["error"] == "blocked_without_tool_failure"
    assert "tools exposed to you are part of your capabilities" in delegate.calls[1]["system"].lower()


@pytest.mark.asyncio
async def test_real_tool_failure_allows_blocked_without_retry() -> None:
    expected = ModelTurn(final_answer="The OS denied the operation.", final_answer_kind="blocked")
    delegate = ScriptedChatModel([expected])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="do the system task",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("terminal_command"),
        tool_history=[
            {
                "tool": "terminal_command",
                "arguments": {"command": "example"},
                "result": {"ok": False, "returncode": 5, "stderr": "Access denied"},
            }
        ],
    )

    assert turn is expected
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_nonzero_returncode_counts_as_real_failure() -> None:
    expected = ModelTurn(final_answer="The command failed.", final_answer_kind="blocked")
    delegate = ScriptedChatModel([expected])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="do the task",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("terminal_command"),
        tool_history=[
            {
                "tool": "terminal_command",
                "arguments": {"command": "example"},
                "result": {"returncode": 1},
            }
        ],
    )

    assert turn is expected
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_guard_failures_do_not_count_as_real_tool_failure() -> None:
    delegate = ScriptedChatModel([
        ModelTurn(final_answer="Blocked.", final_answer_kind="blocked"),
        ModelTurn(tool_calls=[ToolCall(tool="terminal_command", arguments={"command": "echo retry"})]),
    ])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="do the task",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("terminal_command"),
        tool_history=[
            {
                "tool": "execution_guard",
                "arguments": {},
                "result": {"ok": False, "error": "completion_tool_not_run"},
            }
        ],
    )

    assert turn.tool_calls[0].tool == "terminal_command"
    assert len(delegate.calls) == 2


@pytest.mark.asyncio
async def test_ordinary_answer_is_not_text_inspected_or_retried() -> None:
    expected = ModelTurn(final_answer="파일 경로를 알려주세요.", final_answer_kind="answer")
    delegate = ScriptedChatModel([expected])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="수정해줘",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("file_tree", "file_read"),
        tool_history=[],
    )

    assert turn is expected
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_no_tools_means_blocked_is_not_retried() -> None:
    expected = ModelTurn(final_answer="No capability is exposed.", final_answer_kind="blocked")
    delegate = ScriptedChatModel([expected])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="do something external",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=[],
    )

    assert turn is expected
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_retry_is_bounded_when_model_stays_blocked() -> None:
    second = ModelTurn(final_answer="Still blocked.", final_answer_kind="blocked")
    delegate = ScriptedChatModel([
        ModelTurn(final_answer="Blocked.", final_answer_kind="blocked"),
        second,
    ])
    model = AutonomyChatModel(delegate, max_retries=1)

    turn = await model.next_turn(
        system="system",
        user_message="do the task",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("terminal_command"),
        tool_history=[],
    )

    assert turn is second
    assert len(delegate.calls) == 2
