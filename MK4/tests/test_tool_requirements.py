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


def _planner_response() -> str:
    return json.dumps({
        "requirements": [{
            "capability": "current_external_research",
            "satisfying_tools": ["latest_search", "web_research"],
        }]
    })


@pytest.mark.asyncio
async def test_recent_news_request_cannot_finish_without_frozen_search_requirement(monkeypatch) -> None:
    planner_calls = 0
    adequacy_calls = 0

    async def fake_chat(*, system, user, model, response_format):
        nonlocal planner_calls, adequacy_calls
        if "Review whether the successful tool results" in system:
            adequacy_calls += 1
            return json.dumps({"adequate": True, "missing_aspects": []})
        planner_calls += 1
        return _planner_response()

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
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
            system="system\nCurrent date: 2026-08-23.",
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
            system="system\nCurrent date: 2026-08-23.",
            user_message="ADHD와 관련된 최근 뉴스기사가 있어? 있다면 대충 어떤 내용이야?",
            model=None,
            memory_summary=[],
            tool_definitions=definitions,
            tool_history=[{
                "tool": "latest_search",
                "arguments": {"query": "ADHD 최신 뉴스"},
                "result": {
                    "ok": True,
                    "freshness": "recent_news",
                    "results": [{
                        "title": "Recent ADHD research",
                        "snippet": "2026-08-20 — new ADHD study",
                    }],
                },
            }],
        )
        assert second.final_answer == "검색 결과를 바탕으로 최근 ADHD 기사를 요약합니다."
        assert planner_calls == 1
        assert adequacy_calls == 1
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_out_of_window_search_results_force_more_exploration(monkeypatch) -> None:
    adequacy_answers = iter([
        {
            "adequate": False,
            "missing_aspects": [
                "최근 6개월 범위에 해당하는 할리우드 배우 논란 사례가 확인되지 않음",
                "기간 내 사례의 배우 이름과 논란 내용이 확인되지 않음",
            ],
        },
        {"adequate": True, "missing_aspects": []},
    ])

    async def fake_chat(*, system, user, model, response_format):
        if "Review whether the successful tool results" in system:
            return json.dumps(next(adequacy_answers), ensure_ascii=False)
        return _planner_response()

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="검색 결과에 여러 배우 논란이 있었습니다."),
        ModelTurn(tool_calls=[ToolCall(
            tool="web_research",
            arguments={"objective": "2026년 2월 23일 이후 할리우드 배우 논란 사례 확인"},
        )]),
        ModelTurn(final_answer="최근 6개월 범위에서 확인된 배우 논란을 정리합니다."),
    ])
    guarded = ToolRequirementGuardChatModel(delegate)
    definitions = [
        _definition("latest_search", "Search recent news."),
        _definition("web_research", "Research public web sources."),
    ]
    stale_history = [{
        "tool": "latest_search",
        "arguments": {"query": "최근 6개월 내 할리우드 논란 배우"},
        "result": {
            "ok": True,
            "freshness": "recent_news",
            "results": [
                {
                    "title": "AI 여배우 틸리 노우드 논란",
                    "snippet": "Thu, 02 Oct 2025 07:00:00 GMT — 할리우드 비판 여론",
                },
                {
                    "title": "앤 해서웨이·제니퍼 로페즈 인성 논란",
                    "snippet": "Mon, 04 Nov 2024 08:00:00 GMT — 스태프 관련 논란",
                },
            ],
        },
    }]

    token = start_tool_requirement_scope()
    try:
        first = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내에 할리우드에서 논란이 있었는지 확인하고, 있다면 어떤 배우인지도 확인해줄래?",
            model=None,
            memory_summary=[],
            tool_definitions=definitions,
            tool_history=stale_history,
        )
        assert first.tool_calls == [ToolCall(
            tool="web_research",
            arguments={"objective": "2026년 2월 23일 이후 할리우드 배우 논란 사례 확인"},
        )]
        adequacy_guard = delegate.calls[1]["tool_history"][-1]
        assert adequacy_guard["tool"] == "tool_result_adequacy_guard"
        assert adequacy_guard["result"]["error"] == "tool_results_inadequate"
        assert adequacy_guard["result"]["missing_aspects"]

        expanded_history = [
            *stale_history,
            {
                "tool": "web_research",
                "arguments": {"objective": "2026년 2월 23일 이후 할리우드 배우 논란 사례 확인"},
                "result": {
                    "ok": True,
                    "results": [{
                        "title": "Qualifying controversy",
                        "snippet": "2026-06-12 — actor controversy details",
                    }],
                },
            },
        ]
        second = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내에 할리우드에서 논란이 있었는지 확인하고, 있다면 어떤 배우인지도 확인해줄래?",
            model=None,
            memory_summary=[],
            tool_definitions=definitions,
            tool_history=expanded_history,
        )
        assert second.final_answer == "최근 6개월 범위에서 확인된 배우 논란을 정리합니다."
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_stable_concept_question_can_finish_without_tools_or_adequacy_review(monkeypatch) -> None:
    review_calls = 0

    async def fake_chat(*, system, user, model, response_format):
        nonlocal review_calls
        if "Review whether the successful tool results" in system:
            review_calls += 1
            raise AssertionError("adequacy review should not run without frozen tool requirements")
        return json.dumps({"requirements": []})

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
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
        assert review_calls == 0
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
