from __future__ import annotations

import json
from typing import Any

import pytest

from MK4.tools import tool_requirements
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_requirements import (
    FrozenToolRequirements,
    ToolEvaluation,
    ToolRequirementGroup,
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


def _news_plan() -> dict[str, Any]:
    return {
        "tool_evaluations": [
            {"tool": "latest_search", "required": True},
            {"tool": "market_snapshot", "required": False},
            {"tool": "recall_memory", "required": False},
            {"tool": "web_research", "required": True},
        ],
        "required_groups": [
            {"tools": ["latest_search", "web_research"]},
        ],
    }


def _news_definitions() -> list[ToolDefinition]:
    return [
        _definition("latest_search", "Search recent news."),
        _definition("market_snapshot", "Fetch market data."),
        _definition("recall_memory", "Search persistent memory."),
        _definition("web_research", "Research public web sources."),
    ]


@pytest.mark.asyncio
async def test_planner_evaluates_each_tool_and_groups_only_required_alternatives(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["system"] = system
        captured["payload"] = json.loads(user)
        captured["schema"] = response_format
        return json.dumps(_news_plan())

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)

    plan = await tool_requirements.plan_tool_requirements(
        user_message="최근 6개월 내 할리우드 논란 배우가 있었는지 확인해줘",
        model=None,
        memory_summary=["예전에 할리우드 배우 이야기를 한 적이 있음"],
        tool_definitions=_news_definitions(),
    )

    assert [(item.tool, item.required) for item in plan.evaluations] == [
        ("latest_search", True),
        ("market_snapshot", False),
        ("recall_memory", False),
        ("web_research", True),
    ]
    assert [group.tools for group in plan.groups] == [
        ("latest_search", "web_research"),
    ]
    assert captured["payload"]["automatic_memory_context"] == {
        "source": "automatic_graph_activation",
        "already_available_before_tool_use": True,
        "items": ["예전에 할리우드 배우 이야기를 한 적이 있음"],
    }
    assert "do not invent capabilities" in captured["system"].lower()


@pytest.mark.asyncio
async def test_automatic_memory_can_make_explicit_recall_unnecessary(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        payload = json.loads(user)
        assert payload["automatic_memory_context"]["items"] == [
            "사용자는 예전에 SF 소설 A와 B를 추천받았다."
        ]
        return json.dumps({
            "tool_evaluations": [
                {"tool": "recall_memory", "required": False},
                {"tool": "web_research", "required": False},
            ],
            "required_groups": [],
        })

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)

    plan = await tool_requirements.plan_tool_requirements(
        user_message="전에 추천했던 SF 책 기억나?",
        model=None,
        memory_summary=["사용자는 예전에 SF 소설 A와 B를 추천받았다."],
        tool_definitions=[
            _definition("recall_memory", "Search persistent memory."),
            _definition("web_research", "Research public web sources."),
        ],
    )

    assert plan.required is False
    assert plan.groups == ()


@pytest.mark.asyncio
async def test_stale_memory_does_not_remove_current_external_requirement(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        payload = json.loads(user)
        assert payload["automatic_memory_context"]["items"] == ["삼성전자 PER은 예전에 12.6배였다."]
        return json.dumps({
            "tool_evaluations": [
                {"tool": "market_snapshot", "required": True},
                {"tool": "recall_memory", "required": False},
                {"tool": "web_research", "required": False},
            ],
            "required_groups": [
                {"tools": ["market_snapshot"]},
            ],
        })

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)

    plan = await tool_requirements.plan_tool_requirements(
        user_message="삼성전자 지금 PER이 얼마야?",
        model=None,
        memory_summary=["삼성전자 PER은 예전에 12.6배였다."],
        tool_definitions=[
            _definition("market_snapshot", "Fetch market data."),
            _definition("recall_memory", "Search persistent memory."),
            _definition("web_research", "Research public web sources."),
        ],
    )

    assert [group.tools for group in plan.groups] == [("market_snapshot",)]


def test_requirement_plan_rejects_missing_tool_evaluation() -> None:
    with pytest.raises(RuntimeError, match="evaluate every exposed tool exactly once"):
        tool_requirements._parse_requirement_plan(
            {
                "tool_evaluations": [
                    {"tool": "latest_search", "required": True},
                ],
                "required_groups": [{"tools": ["latest_search"]}],
            },
            tool_names=["latest_search", "web_research"],
        )


def test_requirement_plan_rejects_false_tool_inside_group() -> None:
    with pytest.raises(RuntimeError, match="required=false"):
        tool_requirements._parse_requirement_plan(
            {
                "tool_evaluations": [
                    {"tool": "latest_search", "required": True},
                    {"tool": "market_snapshot", "required": False},
                ],
                "required_groups": [
                    {"tools": ["latest_search", "market_snapshot"]},
                ],
            },
            tool_names=["latest_search", "market_snapshot"],
        )


def test_requirement_plan_rejects_required_tool_missing_from_groups() -> None:
    with pytest.raises(RuntimeError, match="must appear in exactly one required group"):
        tool_requirements._parse_requirement_plan(
            {
                "tool_evaluations": [
                    {"tool": "latest_search", "required": True},
                    {"tool": "web_research", "required": True},
                ],
                "required_groups": [
                    {"tools": ["latest_search"]},
                ],
            },
            tool_names=["latest_search", "web_research"],
        )


def test_requirement_plan_rejects_tool_in_multiple_groups() -> None:
    with pytest.raises(RuntimeError, match="only one group"):
        tool_requirements._parse_requirement_plan(
            {
                "tool_evaluations": [
                    {"tool": "latest_search", "required": True},
                    {"tool": "web_research", "required": True},
                ],
                "required_groups": [
                    {"tools": ["latest_search", "web_research"]},
                    {"tools": ["web_research"]},
                ],
            },
            tool_names=["latest_search", "web_research"],
        )


def test_missing_groups_are_and_across_groups_or_within_group() -> None:
    requirements = FrozenToolRequirements(
        evaluations=(
            ToolEvaluation(tool="latest_search", required=True),
            ToolEvaluation(tool="web_research", required=True),
            ToolEvaluation(tool="file_read", required=True),
        ),
        groups=(
            ToolRequirementGroup(tools=("latest_search", "web_research")),
            ToolRequirementGroup(tools=("file_read",)),
        ),
    )

    history = [{
        "tool": "web_research",
        "arguments": {"objective": "recent controversy"},
        "result": {"ok": True, "results": [{"title": "result"}]},
    }]

    missing = tool_requirements.missing_required_groups(requirements, history)
    assert [group.tools for group in missing] == [("file_read",)]


@pytest.mark.asyncio
async def test_recent_news_request_retries_until_one_alternative_group_tool_runs(monkeypatch) -> None:
    planner_calls = 0
    adequacy_calls = 0

    async def fake_chat(*, system, user, model, response_format):
        nonlocal planner_calls, adequacy_calls
        if "Review whether the successful tool results" in system:
            adequacy_calls += 1
            return json.dumps({"adequate": True, "missing_aspects": []})
        planner_calls += 1
        return json.dumps(_news_plan())

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="직접 뉴스 검색을 해보세요."),
        ModelTurn(tool_calls=[ToolCall(tool="latest_search", arguments={"query": "Hollywood controversy 2026"})]),
        ModelTurn(final_answer="검색 결과를 바탕으로 정리합니다."),
    ])
    guarded = ToolRequirementGuardChatModel(delegate)

    token = start_tool_requirement_scope()
    try:
        first = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내 할리우드 논란 배우를 확인해줘",
            model=None,
            memory_summary=[],
            tool_definitions=_news_definitions(),
            tool_history=[],
        )
        assert first.tool_calls == [
            ToolCall(tool="latest_search", arguments={"query": "Hollywood controversy 2026"})
        ]
        guard_event = delegate.calls[1]["tool_history"][-1]
        assert guard_event["tool"] == "tool_requirement_guard"
        assert guard_event["result"]["missing_groups"] == [
            {"tools": ["latest_search", "web_research"]}
        ]

        second = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내 할리우드 논란 배우를 확인해줘",
            model=None,
            memory_summary=[],
            tool_definitions=_news_definitions(),
            tool_history=[{
                "tool": "latest_search",
                "arguments": {"query": "Hollywood controversy 2026"},
                "result": {
                    "ok": True,
                    "results": [{"title": "2026 controversy", "snippet": "2026-06-12"}],
                },
            }],
        )
        assert second.final_answer == "검색 결과를 바탕으로 정리합니다."
        assert planner_calls == 1
        assert adequacy_calls == 1
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_out_of_window_results_still_trigger_adequacy_exploration(monkeypatch) -> None:
    adequacy_answers = iter([
        {
            "adequate": False,
            "missing_aspects": ["최근 6개월 범위의 사례가 확인되지 않음"],
        },
        {"adequate": True, "missing_aspects": []},
    ])

    async def fake_chat(*, system, user, model, response_format):
        if "Review whether the successful tool results" in system:
            return json.dumps(next(adequacy_answers), ensure_ascii=False)
        return json.dumps(_news_plan())

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="검색 결과를 정리합니다."),
        ModelTurn(tool_calls=[ToolCall(
            tool="web_research",
            arguments={"objective": "2026-02-23 이후 할리우드 배우 논란"},
        )]),
        ModelTurn(final_answer="최근 6개월 사례를 정리합니다."),
    ])
    guarded = ToolRequirementGuardChatModel(delegate)
    stale_history = [{
        "tool": "latest_search",
        "arguments": {"query": "할리우드 논란 배우"},
        "result": {
            "ok": True,
            "results": [{
                "title": "Old controversy",
                "snippet": "2024-11-04 — old result",
            }],
        },
    }]

    token = start_tool_requirement_scope()
    try:
        first = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내 할리우드 논란 배우를 확인해줘",
            model=None,
            memory_summary=[],
            tool_definitions=_news_definitions(),
            tool_history=stale_history,
        )
        assert first.tool_calls == [ToolCall(
            tool="web_research",
            arguments={"objective": "2026-02-23 이후 할리우드 배우 논란"},
        )]
        adequacy_guard = delegate.calls[1]["tool_history"][-1]
        assert adequacy_guard["tool"] == "tool_result_adequacy_guard"

        second = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내 할리우드 논란 배우를 확인해줘",
            model=None,
            memory_summary=[],
            tool_definitions=_news_definitions(),
            tool_history=[
                *stale_history,
                {
                    "tool": "web_research",
                    "arguments": {"objective": "2026-02-23 이후 할리우드 배우 논란"},
                    "result": {
                        "ok": True,
                        "results": [{"title": "Current controversy", "snippet": "2026-06-12"}],
                    },
                },
            ],
        )
        assert second.final_answer == "최근 6개월 사례를 정리합니다."
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_stable_concept_question_remains_tool_free(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        if "Review whether the successful tool results" in system:
            raise AssertionError("adequacy review should not run without required groups")
        return json.dumps({
            "tool_evaluations": [
                {"tool": "web_research", "required": False},
            ],
            "required_groups": [],
        })

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    guarded = ToolRequirementGuardChatModel(SequenceChatModel([
        ModelTurn(final_answer="PER은 주가를 주당순이익으로 나눈 값입니다."),
    ]))

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
    finally:
        reset_tool_requirement_scope(token)


def test_failed_tool_event_does_not_satisfy_required_group() -> None:
    requirements = FrozenToolRequirements(
        evaluations=(
            ToolEvaluation(tool="latest_search", required=True),
            ToolEvaluation(tool="web_research", required=True),
        ),
        groups=(ToolRequirementGroup(tools=("latest_search", "web_research")),),
    )
    missing = tool_requirements.missing_required_groups(
        requirements,
        [{
            "tool": "latest_search",
            "arguments": {"query": "ADHD"},
            "result": {"ok": False, "error": "network_failed"},
        }],
    )
    assert [group.tools for group in missing] == [("latest_search", "web_research")]
