from __future__ import annotations

import json
from typing import Any

import pytest

from MK4.tools import grounding_tools
from MK4.tools.grounding_tools import EvidenceGroundingChatModel
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolCall, ToolDefinition
from MK4.tools.web_grounding import web_evidence_catalog


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
            "tool_definitions": list(tool_definitions),
            "tool_history": list(tool_history),
        })
        return self._turns.pop(0)


def _latest_search_history() -> list[dict[str, Any]]:
    return [{
        "tool": "latest_search",
        "arguments": {"query": "최신 SF 소설"},
        "result": {
            "ok": True,
            "freshness": "recent_news",
            "results": [
                {
                    "title": "SF소설 '몰록' 낸 듀나",
                    "url": "https://example.com/molok",
                    "snippet": "2026년 듀나의 SF소설 몰록 출간 인터뷰",
                    "source": "news",
                    "query_node": "최신 SF 소설",
                },
                {
                    "title": "2026년 상반기 베스트셀러 동향",
                    "url": "https://example.com/bestseller",
                    "snippet": "상반기 출판 동향을 정리한다.",
                    "source": "news",
                    "query_node": "최신 SF 소설",
                },
            ],
        },
    }]


def _market_snapshot_history() -> list[dict[str, Any]]:
    return [{
        "tool": "market_snapshot",
        "arguments": {"query": "삼성전자"},
        "result": {
            "ok": True,
            "type": "stock",
            "query": "삼성전자",
            "quote": {"price": 80000, "currency": "KRW"},
        },
    }]


def _grounded_response() -> str:
    return json.dumps({
        "grounded": True,
        "task_aligned": True,
        "missing_aspects": [],
    }, ensure_ascii=False)


def _ungrounded_response(*missing: str) -> str:
    return json.dumps({
        "grounded": False,
        "task_aligned": True,
        "missing_aspects": list(missing),
    }, ensure_ascii=False)


def test_web_evidence_catalog_uses_structural_ids() -> None:
    catalog = web_evidence_catalog(_latest_search_history())
    assert set(catalog) == {"web:0:result:0", "web:0:result:1"}


@pytest.mark.asyncio
async def test_grounding_reviewer_reports_missing_evidence_then_agent_chooses_tool(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_review(*, system, user, model, response_format):
        captured["system"] = system
        captured["payload"] = json.loads(user)
        captured["schema"] = response_format
        return _ungrounded_response("삼성전자의 현재 주가와 PER을 뒷받침하는 현재 근거")

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="삼성전자의 현재 주가는 281,500원이며 PER은 12.6배입니다."),
        ModelTurn(tool_calls=[ToolCall(tool="market_snapshot", arguments={"query": "삼성전자"})]),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="삼성전자의 현재 주가와 PER을 알려줘",
        model=None,
        memory_summary=[],
        tool_definitions=[ToolDefinition(
            name="market_snapshot",
            description="Fetch current market data.",
            input_schema={"type": "object"},
        )],
        tool_history=[],
    )

    assert turn.tool_calls == [ToolCall(tool="market_snapshot", arguments={"query": "삼성전자"})]
    assert "tool_catalog" not in captured["payload"]
    assert set(captured["schema"]["properties"]) == {"grounded", "task_aligned", "missing_aspects"}
    assert "cannot call tools" in captured["system"].lower()
    assert "rewrite the answer" in captured["system"].lower()

    review_event = delegate.calls[1]["tool_history"][-1]
    assert review_event["tool"] == "evidence_grounding_guard"
    assert review_event["result"]["error"] == "final_evidence_insufficient"
    assert review_event["result"]["missing_aspects"] == [
        "삼성전자의 현재 주가와 PER을 뒷받침하는 현재 근거"
    ]
    assert review_event["result"]["successful_external_tools"] == []


@pytest.mark.asyncio
async def test_company_per_value_is_reviewed_as_missing_without_direct_tool_choice(monkeypatch) -> None:
    async def fake_review(*, system, user, model, response_format):
        payload = json.loads(user)
        assert payload["proposed_response"] == "삼성전자의 PER은 12.6배입니다."
        return _ungrounded_response("삼성전자의 현재 PER을 뒷받침하는 현재 근거")

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="삼성전자의 PER은 12.6배입니다."),
        ModelTurn(tool_calls=[ToolCall(
            tool="web_research",
            arguments={"objective": "삼성전자 현재 PER 확인"},
        )]),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="삼성전자의 PER은 얼마야?",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=[],
    )

    assert turn.tool_calls == [ToolCall(
        tool="web_research",
        arguments={"objective": "삼성전자 현재 PER 확인"},
    )]
    assert len(delegate.calls) == 2


@pytest.mark.asyncio
async def test_current_market_answer_is_marked_tool_backed_after_judgment_only_review(monkeypatch) -> None:
    async def fake_review(*, system, user, model, response_format):
        payload = json.loads(user)
        assert payload["successful_external_tools"] == ["market_snapshot"]
        return _grounded_response()

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="삼성전자의 현재 주가는 80,000원입니다."),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="삼성전자의 현재 주가를 알려줘",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=_market_snapshot_history(),
    )

    assert len(delegate.calls) == 1
    assert turn.final_answer == "삼성전자의 현재 주가는 80,000원입니다."
    assert turn.final_answer_kind == "tool_completion"
    assert turn.completion_tools == ["market_snapshot"]


@pytest.mark.asyncio
async def test_non_time_sensitive_answer_can_pass_review_without_tools(monkeypatch) -> None:
    async def fake_review(*, system, user, model, response_format):
        return _grounded_response()

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="PER은 주가를 주당순이익으로 나눈 값입니다."),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="PER이 뭐야?",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=[],
    )

    assert len(delegate.calls) == 1
    assert turn.final_answer == "PER은 주가를 주당순이익으로 나눈 값입니다."
    assert turn.final_answer_kind == "answer"
    assert turn.completion_tools == []


@pytest.mark.asyncio
async def test_insufficient_existing_evidence_returns_missing_aspects_to_agent(monkeypatch) -> None:
    async def fake_review(*, system, user, model, response_format):
        payload = json.loads(user)
        assert payload["successful_external_tools"] == ["latest_search"]
        return _ungrounded_response("추천 후보의 실존 여부, 저자, 줄거리를 뒷받침하는 근거")

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="검색을 통해 여러 신작의 저자와 줄거리까지 확인했습니다."),
        ModelTurn(tool_calls=[ToolCall(
            tool="web_research",
            arguments={"objective": "추천 후보 SF 소설의 실존 여부, 저자, 줄거리 검증"},
        )]),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="실제로 있는 SF 소설을 검증해서 추천해줘",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=_latest_search_history(),
    )

    assert turn.tool_calls == [ToolCall(
        tool="web_research",
        arguments={"objective": "추천 후보 SF 소설의 실존 여부, 저자, 줄거리 검증"},
    )]
    guard = delegate.calls[1]["tool_history"][-1]["result"]
    assert guard["missing_aspects"] == ["추천 후보의 실존 여부, 저자, 줄거리를 뒷받침하는 근거"]


@pytest.mark.asyncio
async def test_successful_search_evidence_passes_original_draft_without_second_agent_call(monkeypatch) -> None:
    async def fake_review(*, system, user, model, response_format):
        return _grounded_response()

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    delegate = SequenceChatModel([
        ModelTurn(final_answer="검색 결과에서 확인되는 작품은 듀나의 《몰록》입니다."),
    ])
    grounded = EvidenceGroundingChatModel(delegate)

    turn = await grounded.next_turn(
        system="system",
        user_message="검증해서 추천해줘",
        model=None,
        memory_summary=[],
        tool_definitions=[],
        tool_history=_latest_search_history(),
    )

    assert len(delegate.calls) == 1
    assert turn.final_answer == "검색 결과에서 확인되는 작품은 듀나의 《몰록》입니다."
    assert turn.final_answer_kind == "tool_completion"
    assert turn.completion_tools == ["latest_search"]


@pytest.mark.asyncio
async def test_grounding_contract_failure_is_visible(monkeypatch) -> None:
    async def fake_review(*, system, user, model, response_format):
        return json.dumps({
            "grounded": False,
            "task_aligned": True,
            "missing_aspects": [],
        })

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_review)
    grounded = EvidenceGroundingChatModel(SequenceChatModel([
        ModelTurn(final_answer="현재 사실을 단정한 초안"),
    ]))

    with pytest.raises(RuntimeError, match="must explain at least one missing aspect"):
        await grounded.next_turn(
            system="system",
            user_message="현재 사실을 알려줘",
            model=None,
            memory_summary=[],
            tool_definitions=[],
            tool_history=[],
        )
