from __future__ import annotations

import json
from typing import Any

import pytest

from MK4.tools import tool_requirements
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_requirements import (
    FrozenToolRequirements,
    ToolEvaluation,
    ToolRequirementGuardChatModel,
    ToolRequirementPlanError,
    freeze_tool_requirements,
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
        self.calls.append({
            "system": system,
            "memory_summary": list(memory_summary),
            "tool_history": list(tool_history),
        })
        return self.turns.pop(0)


def _definition(name: str, description: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
    )


def _news_plan() -> dict[str, Any]:
    return {
        "tool_requirements": {
            "latest_search": True,
            "market_snapshot": False,
            "recall_memory": False,
            "web_research": True,
        },
    }


def _news_definitions() -> list[ToolDefinition]:
    return [
        _definition("latest_search", "Search recent news."),
        _definition("market_snapshot", "Fetch market data."),
        _definition("recall_memory", "Search persistent memory."),
        _definition("web_research", "Research public web sources."),
    ]


@pytest.mark.asyncio
async def test_planner_judges_each_tool_without_automatic_memory_or_groups(monkeypatch) -> None:
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
        current_date="2026-08-23",
        tool_definitions=_news_definitions(),
    )

    assert [(item.tool, item.required) for item in plan.evaluations] == [
        ("latest_search", True),
        ("market_snapshot", False),
        ("recall_memory", False),
        ("web_research", True),
    ]
    assert plan.required_tools == ("latest_search", "web_research")
    assert captured["payload"] == {
        "user_request": "최근 6개월 내 할리우드 논란 배우가 있었는지 확인해줘",
        "current_date": "2026-08-23",
        "tool_catalog": captured["payload"]["tool_catalog"],
    }
    assert "automatic_memory" not in json.dumps(captured["payload"])

    schema = captured["schema"]
    assert set(schema["properties"]) == {"tool_requirements"}
    requirements_schema = schema["properties"]["tool_requirements"]
    assert requirements_schema["required"] == [
        "latest_search",
        "market_snapshot",
        "recall_memory",
        "web_research",
    ]
    assert set(requirements_schema["properties"]) == set(requirements_schema["required"])
    assert all(
        property_schema == {"type": "boolean"}
        for property_schema in requirements_schema["properties"].values()
    )
    assert "there is no or/substitution grouping" in captured["system"].lower()
    assert "automatic memory supplied later" in captured["system"].lower()


@pytest.mark.asyncio
async def test_memory_request_can_freeze_explicit_recall_before_automatic_memory(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        payload = json.loads(user)
        assert "automatic_memory_context" not in payload
        return json.dumps({
            "tool_requirements": {
                "recall_memory": True,
                "web_research": False,
            },
        })

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)

    plan = await tool_requirements.plan_tool_requirements(
        user_message="전에 추천했던 SF 책 기억나?",
        model=None,
        tool_definitions=[
            _definition("recall_memory", "Search persistent memory."),
            _definition("web_research", "Research public web sources."),
        ],
    )

    assert plan.required_tools == ("recall_memory",)


@pytest.mark.asyncio
async def test_current_external_fact_prompt_rejects_memory_as_refresh_source(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["system"] = system
        return json.dumps({
            "tool_requirements": {
                "latest_search": True,
                "recall_memory": False,
                "web_research": False,
            },
        })

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    plan = await tool_requirements.plan_tool_requirements(
        user_message="현재 대한민국 대통령 이름이 뭐지?",
        model=None,
        tool_definitions=[
            _definition("latest_search", "Search current public information."),
            _definition("recall_memory", "Search persistent memory."),
            _definition("web_research", "Research public web sources."),
        ],
    )

    assert plan.required_tools == ("latest_search",)
    lowered = captured["system"].lower()
    assert "persistent memory is not a refresh mechanism" in lowered
    assert "differ today from yesterday" in lowered


def test_requirement_plan_rejects_missing_tool_evaluation() -> None:
    with pytest.raises(ToolRequirementPlanError, match="evaluate every exposed tool exactly once"):
        tool_requirements._parse_requirement_plan(
            {"tool_requirements": {"latest_search": True}},
            tool_names=["latest_search", "web_research"],
        )


def test_requirement_plan_rejects_extra_tool_evaluation() -> None:
    with pytest.raises(ToolRequirementPlanError, match="evaluate every exposed tool exactly once"):
        tool_requirements._parse_requirement_plan(
            {
                "tool_requirements": {
                    "latest_search": True,
                    "web_research": False,
                    "invented_tool": True,
                },
            },
            tool_names=["latest_search", "web_research"],
        )


@pytest.mark.asyncio
async def test_planner_contract_error_is_logged_as_requirement_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(tool_requirements.config, "AGENT_DEBUG_LOG", True)
    monkeypatch.setattr(tool_requirements.config, "MODEL_FAILURE_PREVIEW_CHARS", 200)

    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({"tool_requirements": {"latest_search": True}})

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)

    with pytest.raises(ToolRequirementPlanError, match="evaluate every exposed tool exactly once"):
        await tool_requirements.plan_tool_requirements(
            user_message="현재 대한민국 대통령 이름을 확인해줘",
            model=None,
            tool_definitions=[
                _definition("latest_search", "Search recent information."),
                _definition("web_research", "Research public web sources."),
            ],
        )

    stderr = capsys.readouterr().err
    assert "[MK4 requirement] plan_error=" in stderr
    assert "raw_preview=" in stderr


def test_every_true_tool_is_independently_required() -> None:
    requirements = FrozenToolRequirements(
        evaluations=(
            ToolEvaluation(tool="latest_search", required=True),
            ToolEvaluation(tool="web_research", required=True),
            ToolEvaluation(tool="file_read", required=True),
        ),
    )
    history = [{
        "tool": "web_research",
        "arguments": {"objective": "recent controversy"},
        "result": {"ok": True, "results": [{"title": "result"}]},
    }]

    assert tool_requirements.missing_required_tools(requirements, history) == (
        "latest_search",
        "file_read",
    )


@pytest.mark.asyncio
async def test_guard_reports_exact_missing_tools_and_requires_all_true_tools(monkeypatch) -> None:
    adequacy_calls = 0

    async def fake_chat(*, system, user, model, response_format):
        nonlocal adequacy_calls
        assert "Review whether the successful tool results" in system
        adequacy_calls += 1
        return json.dumps({"adequate": True, "missing_aspects": []})

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    requirements = FrozenToolRequirements(
        evaluations=(
            ToolEvaluation(tool="latest_search", required=True),
            ToolEvaluation(tool="web_research", required=True),
        ),
    )
    delegate = SequenceChatModel([
        ModelTurn(final_answer="검색 없이 답합니다."),
        ModelTurn(tool_calls=[
            ToolCall(tool="latest_search", arguments={"query": "Hollywood controversy 2026"}),
            ToolCall(tool="web_research", arguments={"objective": "Hollywood controversy 2026"}),
        ]),
        ModelTurn(final_answer="두 도구 결과를 바탕으로 정리합니다."),
    ])
    guarded = ToolRequirementGuardChatModel(delegate)

    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(requirements)
        first = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내 할리우드 논란 배우를 확인해줘",
            model=None,
            memory_summary=[],
            tool_definitions=_news_definitions(),
            tool_history=[],
        )
        assert [call.tool for call in first.tool_calls] == ["latest_search", "web_research"]
        guard_event = delegate.calls[1]["tool_history"][-1]
        assert guard_event["tool"] == "tool_requirement_guard"
        assert guard_event["result"]["missing_tools"] == ["latest_search", "web_research"]

        second = await guarded.next_turn(
            system="system\nCurrent date: 2026-08-23.",
            user_message="최근 6개월 내 할리우드 논란 배우를 확인해줘",
            model=None,
            memory_summary=[],
            tool_definitions=_news_definitions(),
            tool_history=[
                {
                    "tool": "latest_search",
                    "arguments": {"query": "Hollywood controversy 2026"},
                    "result": {"ok": True, "results": [{"title": "recent"}]},
                },
                {
                    "tool": "web_research",
                    "arguments": {"objective": "Hollywood controversy 2026"},
                    "result": {"ok": True, "results": [{"title": "details"}]},
                },
            ],
        )
        assert second.final_answer == "두 도구 결과를 바탕으로 정리합니다."
        assert adequacy_calls == 1
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_automatic_memory_does_not_satisfy_frozen_recall_requirement() -> None:
    requirements = FrozenToolRequirements(
        evaluations=(ToolEvaluation(tool="recall_memory", required=True),),
    )
    delegate = SequenceChatModel([
        ModelTurn(final_answer="자동 기억에 답이 있으니 그대로 답합니다."),
        ModelTurn(tool_calls=[ToolCall(tool="recall_memory", arguments={"query": "SF 책"})]),
    ])
    guarded = ToolRequirementGuardChatModel(delegate)

    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(requirements)
        turn = await guarded.next_turn(
            system="system",
            user_message="전에 추천했던 SF 책 기억나?",
            model=None,
            memory_summary=["예전에 추천한 책은 A와 B였다."],
            tool_definitions=[_definition("recall_memory", "Search persistent memory.")],
            tool_history=[],
        )
        assert turn.tool_calls == [ToolCall(tool="recall_memory", arguments={"query": "SF 책"})]
        assert delegate.calls[0]["memory_summary"] == ["예전에 추천한 책은 A와 B였다."]
        assert delegate.calls[1]["tool_history"][-1]["result"]["missing_tools"] == ["recall_memory"]
    finally:
        reset_tool_requirement_scope(token)


@pytest.mark.asyncio
async def test_out_of_window_result_still_triggers_adequacy_exploration(monkeypatch) -> None:
    adequacy_answers = iter([
        {
            "adequate": False,
            "missing_aspects": ["최근 6개월 범위의 사례가 확인되지 않음"],
        },
        {"adequate": True, "missing_aspects": []},
    ])

    async def fake_chat(*, system, user, model, response_format):
        assert "Review whether the successful tool results" in system
        return json.dumps(next(adequacy_answers), ensure_ascii=False)

    monkeypatch.setattr(tool_requirements, "ollama_chat", fake_chat)
    requirements = FrozenToolRequirements(
        evaluations=(
            ToolEvaluation(tool="latest_search", required=True),
            ToolEvaluation(tool="web_research", required=False),
        ),
    )
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
            "results": [{"title": "Old controversy", "snippet": "2024-11-04 — old result"}],
        },
    }]

    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(requirements)
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
        assert delegate.calls[1]["tool_history"][-1]["tool"] == "tool_result_adequacy_guard"

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
                    "result": {"ok": True, "results": [{"title": "Current", "snippet": "2026-06-12"}]},
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
            raise AssertionError("adequacy review should not run without required tools")
        return json.dumps({"tool_requirements": {"web_research": False}})

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


def test_failed_tool_event_does_not_satisfy_required_tool() -> None:
    requirements = FrozenToolRequirements(
        evaluations=(
            ToolEvaluation(tool="latest_search", required=True),
            ToolEvaluation(tool="web_research", required=True),
        ),
    )
    missing = tool_requirements.missing_required_tools(
        requirements,
        [{
            "tool": "latest_search",
            "arguments": {"query": "ADHD"},
            "result": {"ok": False, "error": "network_failed"},
        }],
    )
    assert missing == ("latest_search", "web_research")
