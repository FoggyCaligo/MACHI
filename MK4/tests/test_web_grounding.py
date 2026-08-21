from __future__ import annotations

from typing import Any

import pytest

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
            "tool_history": tool_history,
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


def test_web_evidence_catalog_uses_structural_ids() -> None:
    catalog = web_evidence_catalog(_latest_search_history())

    assert set(catalog) == {"web:0:result:0", "web:0:result:1"}
    assert catalog["web:0:result:0"]["scope"] == "search_snippet"
    assert catalog["web:0:result:0"]["title"] == "SF소설 '몰록' 낸 듀나"


@pytest.mark.asyncio
async def test_grounding_review_can_request_more_research_when_snippets_are_insufficient() -> None:
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
    assert len(delegate.calls) == 2
    review_event = delegate.calls[1]["tool_history"][-1]
    assert review_event["tool"] == "web_grounding_guard"
    assert review_event["result"]["available_evidence"][0]["evidence_id"] == "web:0:result:0"


@pytest.mark.asyncio
async def test_grounding_review_accepts_only_existing_evidence_ids() -> None:
    delegate = SequenceChatModel([
        ModelTurn(final_answer="초안"),
        ModelTurn(
            final_answer="검색 결과에서 확인되는 작품은 듀나의 《몰록》입니다.",
            final_answer_kind="tool_completion",
            completion_tools=["web:0:result:0"],
        ),
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

    assert turn.final_answer == "검색 결과에서 확인되는 작품은 듀나의 《몰록》입니다."
    assert turn.final_answer_kind == "answer"
    assert turn.completion_tools == []


@pytest.mark.asyncio
async def test_grounding_review_blocks_unknown_evidence_ids() -> None:
    delegate = SequenceChatModel([
        ModelTurn(final_answer="초안"),
        ModelTurn(
            final_answer="근거 없는 추천",
            final_answer_kind="tool_completion",
            completion_tools=["web:99:result:0"],
        ),
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

    assert turn.final_answer_kind == "blocked"
    assert "근거 연결" in (turn.final_answer or "")
