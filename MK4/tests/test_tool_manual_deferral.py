from __future__ import annotations

from MK4.tools.llm_client import ModelTurn, _require_tool_manuals
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


def definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="tool_manual",
            description="Read a tool manual.",
            input_schema={
                "type": "object",
                "properties": {"tool": {"type": "string"}},
                "required": ["tool"],
            },
        ),
        ToolDefinition(
            name="web_research",
            description="Research a factual objective on the web.",
            input_schema={
                "type": "object",
                "properties": {"objective": {"type": "string"}},
                "required": ["objective"],
            },
        ),
    ]


def test_unfamiliar_valid_call_keeps_original_call_after_manual() -> None:
    turn = _require_tool_manuals(
        ModelTurn(tool_calls=[ToolCall(tool="web_research", arguments={"objective": "hard SF"})]),
        tool_definitions=definitions(),
        tool_history=[],
    )

    assert [(call.tool, call.arguments) for call in turn.tool_calls] == [
        ("tool_manual", {"tool": "web_research"}),
        ("web_research", {"objective": "hard SF"}),
    ]


def test_unfamiliar_call_missing_required_args_is_deferred_until_after_manual() -> None:
    turn = _require_tool_manuals(
        ModelTurn(tool_calls=[ToolCall(tool="web_research", arguments={})]),
        tool_definitions=definitions(),
        tool_history=[],
    )

    assert [(call.tool, call.arguments) for call in turn.tool_calls] == [
        ("tool_manual", {"tool": "web_research"}),
    ]


def test_consulted_tool_with_missing_args_is_not_hidden_by_manual_deferral() -> None:
    turn = _require_tool_manuals(
        ModelTurn(tool_calls=[ToolCall(tool="web_research", arguments={})]),
        tool_definitions=definitions(),
        tool_history=[{
            "tool": "tool_manual",
            "arguments": {"tool": "web_research"},
            "result": {"ok": True, "tool": "web_research"},
        }],
    )

    assert [(call.tool, call.arguments) for call in turn.tool_calls] == [
        ("web_research", {}),
    ]
