from __future__ import annotations

from MK4.tools.llm_client import ModelTurn, _require_tool_manuals
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


def _definitions(*names: str) -> list[ToolDefinition]:
    return [
        *(ToolDefinition(name=name, description=name, input_schema={}) for name in names),
        ToolDefinition(name="tool_manual", description="manual", input_schema={}),
    ]


def test_unconsulted_tool_call_is_deferred_after_manual_lookup() -> None:
    original = ToolCall(
        tool="web_research",
        arguments={"objective": "verify real SF novels and their plots"},
    )
    turn = ModelTurn(tool_calls=[original])

    guarded = _require_tool_manuals(
        turn,
        tool_definitions=_definitions("web_research"),
        tool_history=[],
    )

    assert guarded.tool_calls == [
        ToolCall(tool="tool_manual", arguments={"tool": "web_research"}),
        original,
    ]
    assert guarded.final_answer is None


def test_multiple_unconsulted_tools_keep_original_order_after_manuals() -> None:
    research = ToolCall(tool="web_research", arguments={"objective": "find books"})
    terminal = ToolCall(tool="terminal_command", arguments={"command": "echo ok"})

    guarded = _require_tool_manuals(
        ModelTurn(tool_calls=[research, terminal]),
        tool_definitions=_definitions("web_research", "terminal_command"),
        tool_history=[],
    )

    assert guarded.tool_calls == [
        ToolCall(tool="tool_manual", arguments={"tool": "web_research"}),
        ToolCall(tool="tool_manual", arguments={"tool": "terminal_command"}),
        research,
        terminal,
    ]


def test_consulted_tool_is_not_wrapped_again() -> None:
    original = ToolCall(tool="web_research", arguments={"objective": "find books"})
    turn = ModelTurn(tool_calls=[original])
    history = [{
        "tool": "tool_manual",
        "arguments": {"tool": "web_research"},
        "result": {"ok": True, "tool": "web_research", "input_schema": {}},
    }]

    guarded = _require_tool_manuals(
        turn,
        tool_definitions=_definitions("web_research"),
        tool_history=history,
    )

    assert guarded is turn


def test_duplicate_tool_names_need_only_one_manual_lookup() -> None:
    first = ToolCall(tool="web_research", arguments={"objective": "find books"})
    second = ToolCall(tool="web_research", arguments={"objective": "verify plots"})

    guarded = _require_tool_manuals(
        ModelTurn(tool_calls=[first, second]),
        tool_definitions=_definitions("web_research"),
        tool_history=[],
    )

    assert guarded.tool_calls == [
        ToolCall(tool="tool_manual", arguments={"tool": "web_research"}),
        first,
        second,
    ]
