from __future__ import annotations

from typing import Any

import pytest

from MK4.tools import adequacy_recovery
from MK4.tools.adequacy_recovery import RecoveringToolRequirementGuardChatModel
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_requirements import (
    FrozenToolRequirements,
    ToolEvaluation,
    ToolResultAdequacy,
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
            "tool_history": list(tool_history),
        })
        return self.turns.pop(0)


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} test tool",
        input_schema={"type": "object", "properties": {}},
    )


def _requirements() -> FrozenToolRequirements:
    return FrozenToolRequirements(
        evaluations=(ToolEvaluation(tool="web_research", required=True),),
    )


def _successful_history() -> list[dict[str, Any]]:
    return [{
        "tool": "web_research",
        "arguments": {"objective": "initial research", "language": "ko"},
        "result": {"ok": True, "results": [{"title": "partial evidence"}]},
    }]


@pytest.mark.asyncio
async def test_inadequate_evidence_rejects_final_only_recovery_until_tool_call(monkeypatch) -> None:
    async def fake_adequacy(**kwargs):
        return ToolResultAdequacy(
            adequate=False,
            missing_aspects=("구체적인 제품과 현재 법적 기준의 추가 근거",),
        )

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="첫 검색 결과만으로 답하겠습니다."),
        ModelTurn(final_answer="추가 검색 없이 추천하겠습니다."),
        ModelTurn(tool_calls=[ToolCall(
            tool="web_research",
            arguments={
                "objective": "한국 도검 규정과 부시크래프트 나이프 제품 사양",
                "language": "ko",
            },
        )]),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate, max_recovery_retries=2)

    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(_requirements())
        turn = await guarded.next_turn(
            system="system",
            user_message="한국에서 법적 문제를 최소화할 서바이벌 나이프 3개 추천해줘",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=_successful_history(),
        )
    finally:
        reset_tool_requirement_scope(token)

    assert turn.tool_calls == [ToolCall(
        tool="web_research",
        arguments={
            "objective": "한국 도검 규정과 부시크래프트 나이프 제품 사양",
            "language": "ko",
        },
    )]
    assert len(delegate.calls) == 3
    first_recovery_event = delegate.calls[1]["tool_history"][-1]
    assert first_recovery_event["result"]["evidence_recovery_required"] is True
    second_recovery_event = delegate.calls[2]["tool_history"][-1]
    assert second_recovery_event["result"]["error"] == "evidence_recovery_obligation_unmet"
    assert second_recovery_event["result"]["evidence_recovery_required"] is True


@pytest.mark.asyncio
async def test_inadequate_evidence_stays_visibly_blocked_if_recovery_never_executes_tool(monkeypatch) -> None:
    async def fake_adequacy(**kwargs):
        return ToolResultAdequacy(
            adequate=False,
            missing_aspects=("추가 근거",),
        )

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="초안"),
        ModelTurn(final_answer="검색 없이 최종 답변"),
        ModelTurn(final_answer="그래도 검색 없이 최종 답변"),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate, max_recovery_retries=2)

    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(_requirements())
        turn = await guarded.next_turn(
            system="system",
            user_message="추가 근거가 필요한 요청",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=_successful_history(),
        )
    finally:
        reset_tool_requirement_scope(token)

    assert turn.final_answer_kind == "blocked"
    assert turn.tool_calls == []
    assert "도구 실행이 이루어지지 않아" in turn.final_answer
    assert len(delegate.calls) == 3


@pytest.mark.asyncio
async def test_adequate_evidence_releases_original_final_without_recovery(monkeypatch) -> None:
    async def fake_adequacy(**kwargs):
        return ToolResultAdequacy(adequate=True, missing_aspects=())

    monkeypatch.setattr(adequacy_recovery, "review_tool_result_adequacy", fake_adequacy)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="충분한 근거로 답변합니다."),
    ])
    guarded = RecoveringToolRequirementGuardChatModel(delegate, max_recovery_retries=2)

    token = start_tool_requirement_scope()
    try:
        freeze_tool_requirements(_requirements())
        turn = await guarded.next_turn(
            system="system",
            user_message="충분한 근거가 있는 요청",
            model=None,
            memory_summary=[],
            tool_definitions=[_definition("web_research")],
            tool_history=_successful_history(),
        )
    finally:
        reset_tool_requirement_scope(token)

    assert turn.final_answer == "충분한 근거로 답변합니다."
    assert len(delegate.calls) == 1
