from __future__ import annotations

import json
from typing import Any

import pytest

from MK4.tools import tool_requirements
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_requirements import (
    ToolRequirementGuardChatModel,
    reset_tool_requirement_scope,
    start_tool_requirement_scope,
)
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


class SequenceChatModel:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append({"system": system, "tool_history": list(tool_history)})
        return self.turns.pop(0)


def _definition(name: str, description: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
    )


@pytest.mark.asyncio
async def test_recent_news_request_cannot_finish_without_frozen_search_requirement(monkeypatch) -> None:
    planner_calls = 0

    async def fake_planner_chat(*, system, user, model, response_format):
        nonlocal planner_calls
        planner_calls += 1
        return json.dumps({
            "requirements": [{
                "capability": "current_external_research",
                "satisfying_tools": ["latest_search", "web_research"],
            }]
        })

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_planner_chat)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="네이버 뉴스에서 ADHD 최신 뉴스를 검색해보세요."),
        ModelTurn(tool_calls=[ToolCall(tool="latest_search", arguments={"query": "ADHD 최신 뉴스"})]),
        ModelTurn(final_answer="검색 결과를 바탕으로 최근 ADHD 기사를 요약합니다."),
    ])
    guarded = ToolRequirementGuardChatModel(delegate)
    definitions = [
        _definition("latest_search", "Search recent news."),
        _definition("web_research", "Research public web sources."),
    ]

    token = start_tool_requirement_scope()
    try:
        first = await guarded.next_turn(
            system="system",
            user_message="ADHD와 관련된 최근 뉴스기사가 있어? 있다면 대충 어떤 내용이야?",
            model=None,
            memory_summary=[],
            tool_definitions=definitions,
            tool_history=[],
        )
        assert first.tool_calls == [
            ToolCall(tool="latest_search", arguments={"query": "ADHD 최신 뉴스"})
        ]
        requirement_guard = delegate.calls[1]["tool_history"][-1]
        assert requirement_guard["tool"] == "tool_requirement_guard"
        assert requirement_guard["result"]["error"] == "frozen_tool_requirement_unmet"

        second = await guarded.next_turn(
            system="system",
            user_message="ADHD와 관련된 최근 뉴스기사가 있어? 있다면 대충 어떤 내용이야?",
            model=None,
            memory_summary=[],
            tool_definitions=definitions,
            tool_history=[{
                "tool": "latest_search",
                "arguments": {"query": "ADHD 최신 뉴스"},
                "result": {"ok": True, "results": [{"title": "example"}]},
            }],
        )
        assert second.final_answer == "검색 결과를 바탕으로 최근 ADHD 기사를 요약합니다."
        assert planner_calls == 1
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_stable_concept_question_can_finish_without_tools(monkeypatch) -> None:
    async def fake_planner_chat(*, system, user, model, response_format):
        return json.dumps({"requirements": []})

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_planner_chat)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="PER은 주가를 주당순이익으로 나눈 값입니다."),
    ])
    guarded = ToolRequirementGuardChatModel(delegate)

    token = start_tool_requirement_scope()
    try:
        turn = await guarded.next_turn(
            system="system",
            user_message="PER이 뭐야?",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research", "Research public web sources.")],
            tool_history=[],
        )
        assert turn.final_answer == "PER은 주가를 주당순이익으로 나눈 값입니다."
        assert turn.tool_calls == []
        assert len(delegate.calls) == 1
    finally:
        reset_tool_requirement_scope(token)


def test_failed_tool_event_does_not_satisfy_frozen_requirement() -> None:
    requirements = tool_requirements.FrozenToolRequirements(requirements=(
        tool_requirements.ToolRequirement(
            capability="current_external_research",
            satisfying_tools=("latest_search", "web_research"),
        ),
    ))
    missing = tool_requirements.missing_required_capabilities(
        requirements,
        [{
            "tool": "latest_search",
            "arguments": {"query": "ADHD"},
            "result": {"ok": False, "error": "network_failed"},
        }],
    )
    assert [item.capability for item in missing] == ["current_external_research"]
