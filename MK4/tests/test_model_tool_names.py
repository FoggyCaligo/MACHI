from __future__ import annotations

from typing import Any

import pytest

from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.llm_client import ModelTurn
from MK4.tools.model_tool_names import ModelToolNameAdapter
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


class CaptureModel:
    def __init__(self) -> None:
        self.tool_definitions: list[ToolDefinition] = []
        self.tool_history: list[dict[str, Any]] = []

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
        self.tool_definitions = tool_definitions
        self.tool_history = tool_history
        return ModelTurn(
            tool_calls=[
                ToolCall(tool="tool_manual", arguments={"tool": "recall_memory"}),
                ToolCall(tool="recall_memory", arguments={}),
            ],
            completion_tools=["recall_memory"],
        )


def aliased_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="graph_search",
            description="Recall persistent graph memory.",
            input_schema={
                "x-model-name": "recall_memory",
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        ToolDefinition(
            name="tool_manual",
            description="Read one tool manual.",
            input_schema={
                "type": "object",
                "properties": {"tool": {"type": "string"}},
                "required": ["tool"],
                "additionalProperties": False,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_recall_memory_is_model_visible_but_returns_runtime_graph_search() -> None:
    inner = CaptureModel()
    adapter = ModelToolNameAdapter(inner)
    turn = await adapter.next_turn(
        system="system",
        user_message="what do you remember?",
        model=None,
        memory_summary=[],
        tool_definitions=aliased_definitions(),
        tool_history=[{
            "tool": "tool_manual",
            "arguments": {"tool": "graph_search"},
            "result": {
                "ok": True,
                "tool": "graph_search",
                "available_tools": ["graph_search", "tool_manual"],
            },
        }],
    )

    assert [definition.name for definition in inner.tool_definitions] == [
        "recall_memory",
        "tool_manual",
    ]
    memory_definition = inner.tool_definitions[0]
    assert "x-model-name" not in memory_definition.input_schema

    manual_event = inner.tool_history[0]
    assert manual_event["arguments"]["tool"] == "recall_memory"
    assert manual_event["result"]["tool"] == "recall_memory"
    assert manual_event["result"]["available_tools"] == ["recall_memory", "tool_manual"]

    assert [(call.tool, call.arguments) for call in turn.tool_calls] == [
        ("tool_manual", {"tool": "graph_search"}),
        ("graph_search", {}),
    ]
    assert turn.completion_tools == ["graph_search"]


def test_graph_search_declares_recall_memory_model_name() -> None:
    suite = object.__new__(GraphToolSuite)
    definition = next(
        item
        for item in suite.build_registry().definitions()
        if item.name == "graph_search"
    )
    assert definition.input_schema["x-model-name"] == "recall_memory"
