from __future__ import annotations

from typing import Any

import pytest

from MK4.tools import grounding_tools
from MK4.tools.compact_focused_web_search import (
    _deduplicate_evidence_item,
    _deduplicate_search_result,
)
from MK4.tools.grounding_tools import (
    EvidenceGroundingChatModel,
    GroundingReview,
    reset_grounding_review_scope,
    start_grounding_review_scope,
    store_precomputed_grounding_review,
)
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolDefinition
from MK4.tools.web_grounding import web_evidence_catalog


class FinalChatModel:
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
        return ModelTurn(final_answer="cached final")


@pytest.mark.asyncio
async def test_outer_grounding_reuses_precomputed_parallel_review(monkeypatch) -> None:
    async def unexpected_review(**kwargs):
        raise AssertionError("grounding reviewer should not run twice for the same final")

    monkeypatch.setattr(grounding_tools, "review_final_grounding", unexpected_review)
    token = start_grounding_review_scope()
    try:
        store_precomputed_grounding_review(
            proposed_response="cached final",
            review=GroundingReview(grounded=True, task_aligned=True, missing_aspects=()),
        )
        guarded = EvidenceGroundingChatModel(FinalChatModel())
        turn = await guarded.next_turn(
            system="system",
            user_message="request",
            model=None,
            memory_summary=[],
            tool_definitions=[],
            tool_history=[],
        )
        assert turn.final_answer == "cached final"
    finally:
        reset_grounding_review_scope(token)


def test_web_evidence_dedup_keeps_unique_context_and_removes_exact_repetition() -> None:
    item = {
        "url": "https://example.com/a",
        "title": "Example",
        "matched_sections": ["same paragraph", "second matched paragraph"],
        "excerpt": "same paragraph\nunique surrounding context\nsecond matched paragraph",
        "truncated": False,
    }

    compact = _deduplicate_evidence_item(item)

    assert compact["matched_sections"] == ["same paragraph", "second matched paragraph"]
    assert compact["excerpt_context"] == "unique surrounding context"
    assert "excerpt" not in compact

    catalog = web_evidence_catalog([{
        "tool": "web_research",
        "result": {
            "ok": True,
            "evidence": [compact],
            "results": [],
        },
    }])
    evidence = catalog["web:0:evidence:0"]
    assert evidence["excerpt_context"] == "unique surrounding context"


def test_read_search_result_keeps_source_metadata_without_repeating_page_snippet() -> None:
    item = {
        "title": "Repeated title",
        "url": "https://example.com/a",
        "snippet": "Repeated search snippet",
        "source": "duckduckgo",
        "query_node": "query",
    }

    compact = _deduplicate_search_result(
        item,
        evidence_urls={"https://example.com/a"},
    )

    assert compact == {
        "url": "https://example.com/a",
        "source": "duckduckgo",
        "query_node": "query",
    }
