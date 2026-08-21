from __future__ import annotations

import json

import pytest

from MK4.tools import structured_context_model
from MK4.tools.llm_client import ModelOutputParseError
from MK4.tools.structured_context_model import StructuredContextOllamaToolChatModel
from MK4.tools.tool_runtime import ToolDefinition


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, input_schema={"type": "object"})


@pytest.mark.asyncio
async def test_recall_phase_uses_single_tool_action(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["schema"] = response_format
        return json.dumps({
            "action": "tool",
            "tool": "recall_memory",
            "arguments": {"query": "alice"},
        })

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    turn = await StructuredContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="hello",
        model=None,
        memory_summary=[],
        tool_definitions=[_definition("recall_memory")],
        tool_history=[],
    )
    assert turn.tool_calls[0].tool == "recall_memory"
    assert captured["schema"]["required"] == ["action"]
    assert captured["schema"]["properties"]["action"]["enum"] == ["tool"]


@pytest.mark.asyncio
async def test_work_phase_accepts_direct_answer_action(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        assert set(response_format["properties"]["action"]["enum"]) == {"tool", "answer"}
        return json.dumps({"action": "answer", "content": "hello back"})

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    turn = await StructuredContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="hello",
        model=None,
        memory_summary=[],
        tool_definitions=[_definition("file_read"), _definition("recall_memory")],
        tool_history=[],
    )
    assert turn.final_answer == "hello back"
    assert turn.tool_calls == []


@pytest.mark.asyncio
async def test_memory_before_mutation_allows_tool_action_only(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        assert response_format["properties"]["action"]["enum"] == ["tool"]
        assert "finish_memory_commit" not in response_format["properties"]["tool"]["enum"]
        return json.dumps({
            "action": "tool",
            "tool": "write_memory",
            "arguments": {},
        })

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    turn = await StructuredContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="commit",
        model=None,
        memory_summary=[],
        tool_definitions=[
            _definition("write_memory"),
            _definition("revise_memory"),
        ],
        tool_history=[],
    )
    assert turn.tool_calls == [turn.tool_calls[0]]
    assert turn.tool_calls[0].tool == "write_memory"


@pytest.mark.asyncio
async def test_memory_done_action_maps_to_finish_tool(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        assert set(response_format["properties"]["action"]["enum"]) == {"tool", "done"}
        return json.dumps({"action": "done"})

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    turn = await StructuredContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="commit",
        model=None,
        memory_summary=[],
        tool_definitions=[
            _definition("write_memory"),
            _definition("revise_memory"),
            _definition("finish_memory_commit"),
        ],
        tool_history=[],
    )
    assert turn.tool_calls[0].tool == "finish_memory_commit"
    assert turn.tool_calls[0].arguments == {}


@pytest.mark.asyncio
async def test_unconsulted_tool_manual_is_a_separate_round(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({
            "action": "tool",
            "tool": "write_memory",
            "arguments": {"subject": {}, "relation": "said", "object": {}},
        })

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    turn = await StructuredContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="commit",
        model=None,
        memory_summary=[],
        tool_definitions=[
            _definition("write_memory"),
            _definition("revise_memory"),
            _definition("tool_manual"),
        ],
        tool_history=[],
    )
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].tool == "tool_manual"
    assert turn.tool_calls[0].arguments == {"tool": "write_memory"}


@pytest.mark.asyncio
async def test_legacy_multi_tool_envelope_cannot_bypass_single_action(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({
            "final_answer": None,
            "tool_calls": [
                {"tool": "write_memory", "arguments": {}},
                {"tool": "revise_memory", "arguments": {}},
            ],
            "final_answer_kind": "answer",
            "completion_tools": [],
        })

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    with pytest.raises(ModelOutputParseError, match="at most one tool call"):
        await StructuredContextOllamaToolChatModel().next_turn(
            system="system",
            user_message="legacy",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("write_memory"), _definition("revise_memory")],
            tool_history=[],
        )


@pytest.mark.asyncio
async def test_legacy_full_envelope_is_still_parsed(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({
            "final_answer": "legacy",
            "tool_calls": [],
            "final_answer_kind": "answer",
            "completion_tools": [],
        })

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    turn = await StructuredContextOllamaToolChatModel().next_turn(
        system="system",
        user_message="legacy",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=[],
    )
    assert turn.final_answer == "legacy"
