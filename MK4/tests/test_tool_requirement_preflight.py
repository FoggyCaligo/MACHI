from __future__ import annotations

import json

import pytest

from MK4.tools import compact_requirement_planner
from MK4.tools.tool_requirement_preflight import plan_and_freeze_before_memory
from MK4.tools.tool_requirements import (
    get_frozen_tool_requirements,
    reset_tool_requirement_scope,
    start_tool_requirement_scope,
)
from MK4.tools.tool_runtime import ToolDefinition


@pytest.mark.asyncio
async def test_preflight_uses_only_user_input_and_tool_result_kinds(monkeypatch) -> None:
    captured: dict[str, object] = {}
    recall_contract = (
        "Return persistent long-term memory records from the user's past conversation, preferences, decisions, "
        "recommendations, and project context. This intentionally exceeds the old 120-character planner cutoff."
    )

    async def fake_chat(*, system, user, model, response_format):
        captured["system"] = system
        captured["payload"] = json.loads(user)
        captured["schema"] = response_format
        return json.dumps({
            "tool_requirements": {
                "latest_search": False,
                "recall_memory": True,
            },
        })

    monkeypatch.setattr(compact_requirement_planner, "ollama_chat", fake_chat)
    definitions = [
        ToolDefinition(
            name="graph_search",
            description=recall_contract,
            input_schema={
                "x-model-name": "recall_memory",
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Invocation-only field description that preflight must not receive.",
                    },
                },
                "required": ["query"],
            },
        ),
        ToolDefinition(
            name="latest_search",
            description="Return recent public news and web source snippets for time-sensitive external facts.",
            input_schema={"type": "object", "properties": {}},
        ),
    ]

    token = start_tool_requirement_scope()
    try:
        plan = await plan_and_freeze_before_memory(
            user_message="전에 추천했던 책 뭐였지?",
            model=None,
            tool_definitions=definitions,
        )
        frozen = get_frozen_tool_requirements()
    finally:
        reset_tool_requirement_scope(token)

    assert plan.required_tools == ("recall_memory",)
    assert frozen == plan
    payload = captured["payload"]
    assert set(payload) == {"user_input", "tools"}
    assert payload["user_input"] == "전에 추천했던 책 뭐였지?"
    assert [item["name"] for item in payload["tools"]] == ["recall_memory", "latest_search"]
    assert all(set(item) == {"name", "result_kind"} for item in payload["tools"])
    assert payload["tools"][0]["result_kind"] == recall_contract
    assert "automatic_memory_context" not in payload
    assert "current_date" not in payload
    assert "input" not in payload["tools"][0]
    assert "call_template" not in payload["tools"][0]

    prompt = str(captured["system"]).lower()
    assert "every exposed tool independently" in prompt
    assert "kind of information or action result" in prompt
    assert "do not compare tools" in prompt
    assert "tool names as semantic shortcuts" in prompt

    schema_properties = captured["schema"]["properties"]["tool_requirements"]["properties"]
    assert set(schema_properties) == {"recall_memory", "latest_search"}
    assert "graph_search" not in schema_properties


@pytest.mark.asyncio
async def test_preflight_true_tools_have_no_substitution_group(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        payload = json.loads(user)
        assert set(payload) == {"user_input", "tools"}
        assert set(response_format["properties"]) == {"tool_requirements"}
        return json.dumps({
            "tool_requirements": {
                "latest_search": True,
                "web_research": True,
            },
        })

    monkeypatch.setattr(compact_requirement_planner, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        plan = await plan_and_freeze_before_memory(
            user_message="최근 사건을 찾고 세부 근거까지 조사해줘",
            model=None,
            tool_definitions=[
                ToolDefinition(
                    name="latest_search",
                    description="Return recent public-news snippets and freshness metadata.",
                    input_schema={"type": "object"},
                ),
                ToolDefinition(
                    name="web_research",
                    description="Return public-web evidence from ranked search results and read source pages.",
                    input_schema={"type": "object"},
                ),
            ],
        )
    finally:
        reset_tool_requirement_scope(token)

    assert plan.required_tools == ("latest_search", "web_research")


@pytest.mark.asyncio
async def test_preflight_product_recommendation_exposes_web_result_kind_without_answer_context(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["payload"] = json.loads(user)
        return json.dumps({
            "tool_requirements": {
                "recall_memory": False,
                "web_research": True,
            },
        })

    monkeypatch.setattr(compact_requirement_planner, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        plan = await plan_and_freeze_before_memory(
            user_message="입문용 만년필 하나를 추천해 줄래?",
            model=None,
            tool_definitions=[
                ToolDefinition(
                    name="recall_memory",
                    description="Return persistent user-specific past conversation and preference memory.",
                    input_schema={"type": "object"},
                ),
                ToolDefinition(
                    name="web_research",
                    description=(
                        "Return current public-web evidence about concrete real-world options from search results and "
                        "read source pages, including facts needed to compare or recommend actual products."
                    ),
                    input_schema={"type": "object"},
                ),
            ],
        )
    finally:
        reset_tool_requirement_scope(token)

    assert plan.required_tools == ("web_research",)
    payload = captured["payload"]
    assert payload["user_input"] == "입문용 만년필 하나를 추천해 줄래?"
    assert all("result_kind" in item for item in payload["tools"])
    assert "memory_summary" not in payload
    assert "tool_history" not in payload
