from __future__ import annotations

from typing import Any

import pytest

from MK5.tools.autonomy_tools import AutonomyChatModel
from MK5.tools.llm_client import ModelTurn
from MK5.tools.tool_runtime import ToolCall, ToolDefinition


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
async def test_routine_file_clarification_is_retried_into_tool_call() -> None:
    delegate = ScriptedChatModel([
        ModelTurn(final_answer="어느 파일인지 알려주시거나 HTML 코드를 붙여넣어 주실 수 있나요?"),
        ModelTurn(tool_calls=[ToolCall(tool="file_tree", arguments={"root": "MK5"})]),
    ])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="UI 헤더를 수정해줘",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("file_tree", "file_read", "file_update"),
        tool_history=[],
    )

    assert turn.tool_calls == [ToolCall(tool="file_tree", arguments={"root": "MK5"})]
    assert len(delegate.calls) == 2
    assert "routine intermediate decision" in delegate.calls[1]["system"]
    retry_history = delegate.calls[1]["tool_history"]
    assert retry_history[-1]["tool"] == "autonomy_guard"
    assert retry_history[-1]["result"]["error"] == "routine_clarification_blocked"


@pytest.mark.asyncio
async def test_routine_process_question_is_retried() -> None:
    delegate = ScriptedChatModel([
        ModelTurn(final_answer="먼저 관련 파일을 찾아볼까요?"),
        ModelTurn(tool_calls=[ToolCall(tool="file_search", arguments={"pattern": "*.html"})]),
    ])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="UI를 수정해줘",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("file_search", "file_read"),
        tool_history=[],
    )

    assert turn.tool_calls[0].tool == "file_search"
    assert len(delegate.calls) == 2


@pytest.mark.asyncio
async def test_material_design_choice_is_not_blocked() -> None:
    expected = ModelTurn(final_answer="헤더 색상은 파란색과 회색 중 어느 쪽을 원하시나요?")
    delegate = ScriptedChatModel([expected])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="헤더 색상을 바꾸고 싶어",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("file_read", "file_update"),
        tool_history=[],
    )

    assert turn is expected
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_destructive_file_question_is_not_blocked() -> None:
    expected = ModelTurn(final_answer="이 설정 파일을 삭제해도 될까요?")
    delegate = ScriptedChatModel([expected])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="정리해줘",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("file_delete", "file_read"),
        tool_history=[],
    )

    assert turn is expected
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_no_workspace_tools_means_no_autonomy_retry() -> None:
    expected = ModelTurn(final_answer="코드 위치를 알려주실 수 있나요?")
    delegate = ScriptedChatModel([expected])
    model = AutonomyChatModel(delegate)

    turn = await model.next_turn(
        system="system",
        user_message="수정해줘",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("graph_search", "web_research"),
        tool_history=[],
    )

    assert turn is expected
    assert len(delegate.calls) == 1


@pytest.mark.asyncio
async def test_retry_is_bounded_when_model_keeps_asking() -> None:
    second = ModelTurn(final_answer="파일 경로를 알려주세요.")
    delegate = ScriptedChatModel([
        ModelTurn(final_answer="어느 파일인지 알려주세요."),
        second,
    ])
    model = AutonomyChatModel(delegate, max_retries=1)

    turn = await model.next_turn(
        system="system",
        user_message="수정해줘",
        model=None,
        memory_summary=[],
        tool_definitions=_tools("file_tree", "file_read"),
        tool_history=[],
    )

    assert turn is second
    assert len(delegate.calls) == 2
