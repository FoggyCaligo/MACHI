from __future__ import annotations

import json

import pytest

from MK4.tools import llm_client
from MK4.tools.llm_client import OllamaToolChatModel
from MK4.tools.tool_catalog import _compact_tool_summary, compact_tool_catalog, missing_required_arguments
from MK4.tools.tool_runtime import ToolDefinition


def test_tool_catalog_contains_compact_invocation_contract() -> None:
    definitions = [
        ToolDefinition(
            name="market_snapshot",
            description="Fetch real-time or delayed market quotes for stocks, indices, and exchange rates.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Stock name, stock code, ticker, index, or exchange-rate pair.",
                    },
                    "detail": {
                        "type": "boolean",
                        "description": "Request optional detail when supported.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
    ]

    catalog = compact_tool_catalog(definitions)

    assert catalog == [{
        "name": "market_snapshot",
        "summary": "Fetch real-time or delayed market quotes for stocks, indices, and exchange rates.",
        "input": [
            {
                "name": "query",
                "type": "string",
                "required": True,
                "description": "Stock name, stock code, ticker, index, or exchange-rate pair.",
            },
            {
                "name": "detail",
                "type": "boolean",
                "required": False,
                "description": "Request optional detail when supported.",
            },
        ],
        "call_template": {
            "tool": "market_snapshot",
            "arguments": {"query": "<string>"},
        },
    }]
    serialized = json.dumps(catalog)
    assert '"properties"' not in serialized
    assert '"additionalProperties"' not in serialized


def test_tool_catalog_compacts_array_type_and_enum() -> None:
    definition = ToolDefinition(
        name="example",
        description="Example tool.",
        input_schema={
            "type": "object",
            "properties": {
                "domains": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": ["a", "b"]},
            },
            "required": [],
        },
    )

    catalog = compact_tool_catalog([definition])[0]

    assert catalog["input"] == [
        {"name": "domains", "type": "array<string>", "required": False},
        {"name": "mode", "type": "string", "required": False, "enum": ["a", "b"]},
    ]
    assert catalog["call_template"] == {"tool": "example", "arguments": {}}


def test_missing_required_arguments_uses_schema_contract() -> None:
    definition = ToolDefinition(
        name="web_research",
        description="Research.",
        input_schema={
            "type": "object",
            "properties": {"objective": {"type": "string"}},
            "required": ["objective"],
        },
    )

    assert missing_required_arguments({}, definition) == ["objective"]
    assert missing_required_arguments({"objective": ""}, definition) == ["objective"]
    assert missing_required_arguments({"objective": "verify"}, definition) == []


def test_tool_summary_is_one_line_and_capped() -> None:
    assert _compact_tool_summary("first\nsecond") == "first second"
    assert len(_compact_tool_summary("x" * 400)) <= 160


@pytest.mark.asyncio
async def test_model_payload_exposes_compact_tool_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["system"] = system
        captured["user"] = user
        return json.dumps({
            "final_answer": "ok",
            "tool_calls": [],
            "final_answer_kind": "answer",
            "completion_tools": [],
        })

    monkeypatch.setattr(llm_client, "ollama_chat", fake_chat)
    definition = ToolDefinition(
        name="graph_search",
        description="Search persistent graph memory.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Memory query."}},
            "required": ["query"],
        },
    )

    turn = await OllamaToolChatModel().next_turn(
        system="base system",
        user_message="remember me",
        model=None,
        memory_summary=["memory first"],
        tool_definitions=[definition],
        tool_history=[],
    )

    payload = json.loads(str(captured["user"]))
    assert list(payload) == [
        "user_message",
        "memory_summary",
        "tool_catalog",
        "tools",
        "tool_history",
    ]
    assert payload["memory_summary"] == ["memory first"]
    assert payload["tool_catalog"] == [{
        "name": "graph_search",
        "summary": "Search persistent graph memory.",
        "input": [{
            "name": "query",
            "type": "string",
            "required": True,
            "description": "Memory query.",
        }],
        "call_template": {"tool": "graph_search", "arguments": {"query": "<string>"}},
    }]
    assert payload["tools"] == ["graph_search"]
    assert captured["system"] == "base system"
    assert turn.final_answer == "ok"
