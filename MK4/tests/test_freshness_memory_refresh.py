from __future__ import annotations

import json
from typing import Any

import pytest

from MK4.tools import grounding_tools
from MK4.tools.grounding_tools import EvidenceGroundingChatModel
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolCall, ToolDefinition


class SequenceChatModel:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self._turns = list(turns)
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
            "user_message": user_message,
            "memory_summary": memory_summary,
            "tool_history": tool_history,
        })
        return self._turns.pop(0)


@pytest.mark.asyncio
async def test_concept_answer_with_memory_backed_current_value_requires_refresh(monkeypatch) -> None:
    proposed = (
        "PER은 주가를 주당순이익으로 나눈 값입니다. "
        "삼성전자의 현재 PER이 약 12.63배라고 가정해보면 적정 수준으로 볼 수 있습니다."
    )

    async def fake_review(*, system, user, model, response_format):
        payload = json.loads(user)
        assert payload["proposed_response"] == proposed
        assert payload["successful_external_tools"] == []
        return json.dumps({
            "grounded": False,
            "missing_aspects": ["삼성전자의 현재 PER을 뒷받침하는 현재 근거"],
        }, ensure_ascii=False)

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer=proposed),
        ModelTurn(tool_calls=[ToolCall(
            tool="web_research",
            arguments={"objective": "삼성전자 현재 PER 확인"},
        )]),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="주식에서 PER이 뭐야?",
        model=None,
        memory_summary=[{
            "label": "삼성전자의 PER은 12.63배입니다.",
            "node_type": "utterance",
            "subgraph": {
                "focus": {
                    "label": "삼성전자의 PER은 12.63배입니다.",
                    "node_type": "utterance",
                    "provenance": "assistant_utterance",
                },
                "relations": [],
            },
        }],
        tool_definitions=[],
        tool_history=[],
    )

    assert turn.tool_calls == [ToolCall(
        tool="web_research",
        arguments={"objective": "삼성전자 현재 PER 확인"},
    )]
    assert len(delegate.calls) == 2
    review_event = delegate.calls[1]["tool_history"][-1]
    assert review_event["tool"] == "evidence_grounding_guard"
    assert review_event["result"]["proposed_response"] == proposed
    assert review_event["result"]["successful_external_tools"] == []
    assert review_event["result"]["missing_aspects"] == [
        "삼성전자의 현재 PER을 뒷받침하는 현재 근거"
    ]


@pytest.mark.asyncio
async def test_pure_concept_answer_still_needs_no_external_tool(monkeypatch) -> None:
    answer = "PER은 주가를 주당순이익으로 나눈 값으로, 이익 대비 주가 수준을 보는 지표입니다."

    async def fake_review(*, system, user, model, response_format):
        payload = json.loads(user)
        assert payload["proposed_response"] == answer
        return json.dumps({
            "grounded": True,
            "missing_aspects": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer=answer),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="주식에서 PER이 뭐야?",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=[],
    )

    assert len(delegate.calls) == 1
    assert turn.final_answer == answer
    assert turn.final_answer_kind == "answer"
    assert turn.completion_tools == []
