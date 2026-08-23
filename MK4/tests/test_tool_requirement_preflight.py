from __future__ import annotations

import json

import pytest

from MK4.tools import tool_requirements
from MK4.tools.tool_requirement_preflight import plan_and_freeze_before_memory
from MK4.tools.tool_requirements import (
    get_frozen_tool_requirements,
    reset_tool_requirement_scope,
    start_tool_requirement_scope,
)
from MK4.tools.tool_runtime import ToolDefinition


@pytest.mark.asyncio
async def test_preflight_uses_model_facing_names_and_no_automatic_memory(monkeypatch) -> None:
    captured: dict[str, object] = {}

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

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    definitions = [
        ToolDefinition(
            name="graph_search",
            description="Recall persistent memory.",
            input_schema={
                "x-model-name": "recall_memory",
                "type": "object",
                "properties": {},
            },
        ),
        ToolDefinition(
            name="latest_search",
            description="Search current public information.",
            input_schema={"type": "object", "properties": {}},
        ),
    ]

    token = start_tool_requirement_scope()
    try:
        plan = await plan_and_freeze_before_memory(
            user_message="전에 추천했던 책 뭐였지?",
            model=None,
            tool_definitions=definitions,
            current_date="2026-08-23",
        )
        frozen = get_frozen_tool_requirements()
    finally:
        reset_tool_requirement_scope(token)

    assert plan.required_tools == ("recall_memory",)
    assert frozen == plan
    payload = captured["payload"]
    assert payload["current_date"] == "2026-08-23"
    assert "automatic_memory_context" not in payload
    assert [item["name"] for item in payload["tool_catalog"]] == ["recall_memory", "latest_search"]
    schema_properties = captured["schema"]["properties"]["tool_requirements"]["properties"]
    assert set(schema_properties) == {"recall_memory", "latest_search"}
    assert "graph_search" not in schema_properties


@pytest.mark.asyncio
async def test_preflight_true_tools_have_no_substitution_group(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        assert set(response_format["properties"]) == {"tool_requirements"}
        return json.dumps({
            "tool_requirements": {
                "latest_search": True,
                "web_research": True,
            },
        })

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    token = start_tool_requirement_scope()
    try:
        plan = await plan_and_freeze_before_memory(
            user_message="최근 사건을 찾고 세부 근거까지 조사해줘",
            model=None,
            tool_definitions=[
                ToolDefinition(
                    name="latest_search",
                    description="Search recent public information.",
                    input_schema={"type": "object"},
                ),
                ToolDefinition(
                    name="web_research",
                    description="Research public evidence in depth.",
                    input_schema={"type": "object"},
                ),
            ],
        )
    finally:
        reset_tool_requirement_scope(token)

    assert plan.required_tools == ("latest_search", "web_research")
