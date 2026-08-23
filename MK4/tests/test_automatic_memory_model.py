from __future__ import annotations

import json

import pytest

from MK4.tools import automatic_memory_model
from MK4.tools.account_authorization import reset_account_role, set_account_role
from MK4.tools.automatic_memory_model import AutomaticMemoryContextOllamaToolChatModel
from MK4.tools.llm_client import ModelOutputParseError
from MK4.tools.tool_requirements import (
    FrozenToolRequirements,
    ToolEvaluation,
    freeze_tool_requirements,
    reset_tool_requirement_scope,
    start_tool_requirement_scope,
)
from MK4.tools.tool_runtime import ToolDefinition


def _light_response(message: str = "ok") -> str:
    return json.dumps({"message": message, "tool_calls": []})


@pytest.mark.asyncio
async def test_automatic_memory_is_separate_from_tool_history(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        captured["response_format"] = response_format
        return _light_response()

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    definition = ToolDefinition(
        name="recall_memory",
        description="Recall persistent memory.",
        input_schema={"type": "object"},
    )

    token = start_tool_requirement_scope()
    try:
        turn = await AutomaticMemoryContextOllamaToolChatModel().next_turn(
            system="system",
            user_message="what do you remember?",
            model=None,
            memory_summary=["automatic node"],
            tool_definitions=[definition],
            tool_history=[],
        )
    finally:
        reset_tool_requirement_scope(token)

    payload = json.loads(str(captured["user"]))
    assert list(payload) == [
        "user_message",
        "authorization_context",
        "frozen_tool_requirements",
        "automatic_memory_context",
        "tool_catalog",
        "tool_history",
    ]
    assert payload["frozen_tool_requirements"]["required_tools"] == []
    assert payload["frozen_tool_requirements"]["missing_tools"] == []
    assert "does not satisfy an explicit tool requirement" in payload["frozen_tool_requirements"]["contract"]
    context = payload["automatic_memory_context"]
    assert context["source"] == "automatic_graph_activation"
    assert context["scope"] == "partial"
    assert context["is_tool_result"] is False
    assert context["items"] == ["automatic node"]
    assert payload["tool_catalog"][0]["name"] == "recall_memory"
    assert payload["tool_history"] == []
    assert turn.final_answer == "ok"

    response_schema = captured["response_format"]
    assert set(response_schema["properties"]) == {"message", "tool_calls"}
    assert response_schema["required"] == ["message", "tool_calls"]
    assert "final_answer" not in response_schema["properties"]
    assert "final_answer_kind" not in response_schema["properties"]
    assert "completion_tools" not in response_schema["properties"]


@pytest.mark.asyncio
async def test_frozen_required_tools_are_visible_even_when_automatic_memory_has_answer(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        return _light_response()

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(FrozenToolRequirements(
            evaluations=(ToolEvaluation(tool="recall_memory", required=True),),
        ))
        await AutomaticMemoryContextOllamaToolChatModel().next_turn(
            system="system",
            user_message="전에 추천한 SF 책 뭐였지?",
            model=None,
            memory_summary=["추천했던 책은 A와 B였다."],
            tool_definitions=[ToolDefinition(
                name="recall_memory",
                description="Recall persistent memory.",
                input_schema={"type": "object"},
            )],
            tool_history=[],
        )
    finally:
        reset_tool_requirement_scope(token)

    payload = json.loads(str(captured["user"]))
    frozen = payload["frozen_tool_requirements"]
    assert frozen["required_tools"] == ["recall_memory"]
    assert frozen["missing_tools"] == ["recall_memory"]
    assert payload["automatic_memory_context"]["items"] == ["추천했던 책은 A와 B였다."]
    assert payload["automatic_memory_context"]["is_tool_result"] is False


@pytest.mark.asyncio
async def test_successful_required_tool_disappears_from_missing_tools(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        return _light_response()

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(FrozenToolRequirements(
            evaluations=(ToolEvaluation(tool="recall_memory", required=True),),
        ))
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
    finally:
        reset_tool_requirement_scope(token)

    payload = json.loads(str(captured["user"]))
    assert payload["frozen_tool_requirements"]["required_tools"] == ["recall_memory"]
    assert payload["frozen_tool_requirements"]["missing_tools"] == []
    assert payload["tool_history"][0]["tool"] == "recall_memory"


@pytest.mark.asyncio
async def test_owner_authorization_context_is_explicit_in_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["user"] = user
        return _light_response()

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    role_token = set_account_role("owner")
    requirement_token = start_tool_requirement_scope()
    try:
        await AutomaticMemoryContextOllamaToolChatModel().next_turn(
            system="system",
            user_message="configure startup",
            model=None,
            memory_summary=[],
            tool_definitions=[],
            tool_history=[],
        )
    finally:
        reset_tool_requirement_scope(requirement_token)
        reset_account_role(role_token)

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
        return _light_response()

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
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
    finally:
        reset_tool_requirement_scope(token)

    payload = json.loads(str(captured["user"]))
    assert payload["automatic_memory_context"]["is_tool_result"] is False
    assert payload["tool_history"][0]["tool"] == "recall_memory"


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapper_key", ["content", "text", "response"])
async def test_single_string_field_nested_object_is_unwrapped(monkeypatch, wrapper_key: str) -> None:
    nested_message = json.dumps({wrapper_key: "안녕하세요"}, ensure_ascii=False)

    async def fake_chat(*, system, user, model, response_format):
        return _light_response(nested_message)

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        turn = await AutomaticMemoryContextOllamaToolChatModel().next_turn(
            system="system",
            user_message="안녕?",
            model=None,
            memory_summary=[],
            tool_definitions=[],
            tool_history=[],
        )
    finally:
        reset_tool_requirement_scope(token)

    assert turn.final_answer == "안녕하세요"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nested_message",
    [
        json.dumps({"content": "안녕하세요", "meta": "extra"}, ensure_ascii=False),
        json.dumps({"content": {"text": "안녕하세요"}}, ensure_ascii=False),
        json.dumps(["안녕하세요"], ensure_ascii=False),
    ],
)
async def test_ambiguous_nested_structured_message_is_contract_failure(monkeypatch, nested_message: str) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return _light_response(nested_message)

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        with pytest.raises(ModelOutputParseError, match="ambiguous"):
            await AutomaticMemoryContextOllamaToolChatModel().next_turn(
                system="system",
                user_message="안녕?",
                model=None,
                memory_summary=[],
                tool_definitions=[],
                tool_history=[],
            )
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_plain_text_that_contains_json_fragment_remains_valid(monkeypatch) -> None:
    answer = '예시는 {"content": "안녕하세요"} 같은 JSON입니다.'

    async def fake_chat(*, system, user, model, response_format):
        return _light_response(answer)

    monkeypatch.setattr(automatic_memory_model, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        turn = await AutomaticMemoryContextOllamaToolChatModel().next_turn(
            system="system",
            user_message="JSON 예시를 보여줘",
            model=None,
            memory_summary=[],
            tool_definitions=[],
            tool_history=[],
        )
    finally:
        reset_tool_requirement_scope(token)

    assert turn.final_answer == answer
