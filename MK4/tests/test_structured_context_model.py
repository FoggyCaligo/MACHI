from __future__ import annotations

import json

import pytest

from MK4.tools import structured_context_model
from MK4.tools.account_authorization import reset_account_role, set_account_role
from MK4.tools.structured_context_model import StructuredContextOllamaToolChatModel
from MK4.tools.tool_runtime import ToolDefinition


@pytest.mark.asyncio
async def test_automatic_memory_is_not_injected_into_model_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        return json.dumps({
            "final_answer": "ok",
            "tool_calls": [],
            "final_answer_kind": "answer",
            "completion_tools": [],
        })

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    definition = ToolDefinition(
        name="recall_memory",
        description="Recall persistent memory.",
        input_schema={"type": "object"},
    )

    await StructuredContextOllamaToolChatModel().next_turn(
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
        "authorization_context",
        "tool_catalog",
        "tool_history",
    ]
    assert "automatic_memory_context" not in payload
    assert "tools" not in payload
    assert payload["tool_catalog"][0]["name"] == "recall_memory"
    assert payload["tool_history"] == []


@pytest.mark.asyncio
async def test_owner_authorization_context_is_explicit_in_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        return json.dumps({
            "final_answer": "ok",
            "tool_calls": [],
            "final_answer_kind": "answer",
            "completion_tools": [],
        })

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)
    token = set_account_role("owner")
    try:
        await StructuredContextOllamaToolChatModel().next_turn(
            system="system",
            user_message="configure startup",
            model=None,
            memory_summary=[],
            tool_definitions=[],
            tool_history=[],
        )
    finally:
        reset_account_role(token)

    payload = json.loads(str(captured["user"]))
    authorization = payload["authorization_context"]
    assert authorization["role"] == "owner"
    assert authorization["tool_access"] == "all_exposed_tools"
    assert authorization["system_changes"] is True
    assert authorization["startup_registration"] is True
    assert authorization["registry"] is True
    assert authorization["permission_rule"] == "attempt_tool_then_trust_real_os_result"


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

    monkeypatch.setattr(structured_context_model, "ollama_chat", fake_chat)

    await StructuredContextOllamaToolChatModel().next_turn(
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
    assert "automatic_memory_context" not in payload
    assert payload["tool_history"][0]["tool"] == "recall_memory"
