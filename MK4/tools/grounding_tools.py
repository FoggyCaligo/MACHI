from __future__ import annotations

from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolDefinition
from .web_grounding import compact_evidence_catalog, web_evidence_catalog


_GROUNDING_REVIEW_INSTRUCTION = """
A web-evidence grounding review is required before this answer can be shown to the user.
Review the proposed answer against the web evidence in tool_history.

Rules:
- Every externally sourced factual statement in the final answer must be directly supported by the selected evidence.
- A `search_snippet` supports only what its title/snippet explicitly says. Do not infer an author, publication date, plot, product detail, or other attribute that is absent from it.
- `page_evidence` may support facts that are explicit in its matched sections/excerpt.
- Do not fill missing facts from memory or invent plausible titles, authors, dates, plots, or verification status.
- If the available evidence does not support enough of the user's request, return tool_calls for additional `web_research` instead of a final answer.
- For this grounding-review response only: when returning a final answer, set `final_answer_kind` to `tool_completion` and put the supporting web evidence IDs in `completion_tools`. Do not put tool names there during this review.
""".strip()


class EvidenceGroundingChatModel:
    """Require an explicit grounding pass after web evidence enters a turn.

    The normal model contract is left unchanged. During the internal grounding
    review only, `completion_tools` is temporarily used as a structured carrier
    for evidence IDs. The wrapper validates those IDs against actual tool history,
    then strips them before the turn reaches the orchestrator. No claim routing or
    semantic decision is made with string matching.
    """

    def __init__(self, delegate: ChatModel) -> None:
        self._delegate = delegate

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
        turn = await self._delegate.next_turn(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )
        catalog = web_evidence_catalog(tool_history)
        if not catalog or turn.tool_calls or not turn.final_answer or turn.final_answer_kind == "blocked":
            return turn

        review_history = [
            *tool_history,
            {
                "tool": "web_grounding_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": "grounding_review_required",
                    "message": _GROUNDING_REVIEW_INSTRUCTION,
                    "proposed_final_answer": turn.final_answer,
                    "available_evidence": compact_evidence_catalog(tool_history),
                },
            },
        ]
        reviewed = await self._delegate.next_turn(
            system=f"{system}\n{_GROUNDING_REVIEW_INSTRUCTION}",
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=review_history,
        )
        if reviewed.tool_calls or not reviewed.final_answer or reviewed.final_answer_kind == "blocked":
            return reviewed

        selected = [evidence_id for evidence_id in reviewed.completion_tools if evidence_id]
        if (
            reviewed.final_answer_kind == "tool_completion"
            and selected
            and all(evidence_id in catalog for evidence_id in selected)
        ):
            return ModelTurn(
                final_answer=reviewed.final_answer,
                final_answer_kind="answer",
                completion_tools=[],
            )

        return ModelTurn(
            final_answer=(
                "웹 검색 결과를 사용했지만 최종 답변의 근거 연결을 검증하지 못해 "
                "답변을 확정하지 않았습니다."
            ),
            final_answer_kind="blocked",
        )
