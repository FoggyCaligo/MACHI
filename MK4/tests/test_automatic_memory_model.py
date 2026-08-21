from __future__ import annotations

import json

import pytest

from MK4.tools import automatic_memory_model
from MK4.tools.automatic_memory_model import AutomaticMemoryContextOllamaToolChatModel
from MK4.tools.tool_runtime import ToolDefinition


@pytest.mark.asyncio
async def test_automatic_memory_is_separate_from_tool_history(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        return json.dumps({
            "final_answer": "ok",
            "tool_calls": [],
            "final_answer_kind": "answer",
            "completion_tools": [],
        })

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    definition = ToolDefinition(
        name="recall_memory",
        description="Recall persistent memory.",
        input_schema={"type": "object"},
    )

    await AutomaticMemoryContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="what do you remember?",
        model=None,
        memory_summary=["automatic node"],
        tool_definitions=[definition],
        tool_history=[],
    )

    payload = json.loads(str(captured["user"]))
    assert list(payload) == [
        "user_message",
        "automatic_memory_context",
        "tool_catalog",
        "tools",
        "tool_history",
    ]
    context = payload["automatic_memory_context"]
    assert context["source"] == "automatic_graph_activation"
    assert context["scope"] == "partial"
    assert context["is_tool_result"] is False
    assert context["items"] == ["automatic node"]
    assert payload["tool_history"] == []


@pytest.mark.asyncio
async def test_recall_memory_result_appears_only_in_tool_history(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        return json.dumps({
            "final_answer": "ok",
            "tool_calls": [],
            "final_answer_kind": "answer",
            "completion_tools": [],
        })

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)

    await AutomaticMemoryContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="remember more",
        model=None,
        memory_summary=["automatic node"],
        tool_definitions=[],
        tool_history=[{
            "tool": "recall_memory",
            "arguments": {},
            "result": {"ok": True, "mode": "browse", "results": []},
        }],
    )

    payload = json.loads(str(captured["user"]))
    assert payload["automatic_memory_context"]["is_tool_result"] is False
    assert payload["tool_history"][0]["tool"] == "recall_memory"
