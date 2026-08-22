from __future__ import annotations

from MK4.tools.automatic_memory_model import _manual_for_incomplete_tool_calls
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


def _definition(name: str, *, required: list[str] | None = None) -> ToolDefinition:
    required_fields = required or []
    return ToolDefinition(
        name=name,
        description=name,
        input_schema={
            "type": "object",
            "properties": {
                field: {"type": "string"}
                for field in required_fields
            },
            "required": required_fields,
        },
    )


def _definitions(*definitions: ToolDefinition) -> list[ToolDefinition]:
    return [
        *definitions,
        ToolDefinition(name="tool_manual", description="manual", input_schema={}),
    ]


def test_complete_tool_call_runs_without_manual_lookup() -> None:
    original = ToolCall(
        tool="web_research",
        arguments={"objective": "verify real SF novels and their plots"},
    )
    turn = ModelTurn(tool_calls=[original])

    guarded = _manual_for_incomplete_tool_calls(
        turn,
        tool_definitions=_definitions(_definition("web_research", required=["objective"])),
        tool_history=[],
    )

    assert guarded is turn
    assert guarded.tool_calls == [original]


def test_missing_required_arguments_trigger_manual_only() -> None:
    incomplete = ToolCall(tool="web_research", arguments={})

    guarded = _manual_for_incomplete_tool_calls(
        ModelTurn(tool_calls=[incomplete]),
        tool_definitions=_definitions(_definition("web_research", required=["objective"])),
        tool_history=[],
    )

    assert guarded.tool_calls == [
        ToolCall(tool="tool_manual", arguments={"tool": "web_research"}),
    ]


def test_complete_calls_still_run_when_another_call_needs_manual() -> None:
    incomplete = ToolCall(tool="web_research", arguments={})
    complete = ToolCall(tool="market_snapshot", arguments={"query": "삼성전자"})

    guarded = _manual_for_incomplete_tool_calls(
        ModelTurn(tool_calls=[incomplete, complete]),
        tool_definitions=_definitions(
            _definition("web_research", required=["objective"]),
            _definition("market_snapshot", required=["query"]),
        ),
        tool_history=[],
    )

    assert guarded.tool_calls == [
        ToolCall(tool="tool_manual", arguments={"tool": "web_research"}),
        complete,
    ]


def test_consulted_tool_is_allowed_after_manual_lookup() -> None:
    incomplete = ToolCall(tool="web_research", arguments={})
    history = [{
        "tool": "tool_manual",
        "arguments": {"tool": "web_research"},
        "result": {"ok": True, "tool": "web_research", "input_schema": {}},
    }]

    guarded = _manual_for_incomplete_tool_calls(
        ModelTurn(tool_calls=[incomplete]),
        tool_definitions=_definitions(_definition("web_research", required=["objective"])),
        tool_history=history,
    )

    assert guarded.tool_calls == [incomplete]
