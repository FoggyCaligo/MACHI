from __future__ import annotations

import json

import pytest

from MK4.tools import llm_client
from MK4.tools.llm_client import OllamaToolChatModel
from MK4.tools.tool_catalog import _compact_tool_summary, compact_tool_catalog
from MK4.tools.tool_runtime import ToolDefinition


def test_tool_catalog_contains_name_and_compact_purpose_without_schema() -> None:
    definitions = [
        ToolDefinition(
            name="graph_search",
            description="Search persistent graph memory for relevant past information. Returns compact graph context.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
        ToolDefinition(
            name="file_read",
            description="Read a file from the current working root.\nUse it before editing a target file.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    ]

    catalog = compact_tool_catalog(definitions)

    assert catalog == [
        {
            "name": "graph_search",
            "summary": "Search persistent graph memory for relevant past information. Returns compact graph context.",
        },
        {
            "name": "file_read",
            "summary": "Read a file from the current working root. Use it before editing a target file.",
        },
    ]
    assert "input_schema" not in json.dumps(catalog)
    assert '"properties"' not in json.dumps(catalog)


def test_tool_summary_is_one_line_and_capped() -> None:
    assert _compact_tool_summary("first\nsecond") == "first second"
    assert len(_compact_tool_summary("x" * 400)) <= 180


@pytest.mark.asyncio
async def test_model_payload_places_memory_before_tool_routing_metadata(monkeypatch) -> None:
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
        input_schema={"type": "object"},
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
    assert payload["tool_catalog"] == [
        {"name": "graph_search", "summary": "Search persistent graph memory."}
    ]
    assert payload["tools"] == ["graph_search"]
    assert captured["system"] == "base system"
    assert turn.final_answer == "ok"
