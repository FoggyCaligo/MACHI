from __future__ import annotations

from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolDefinition
from .web_grounding import compact_evidence_catalog, web_evidence_catalog


_GROUNDING_REVIEW_INSTRUCTION = """
A final-answer evidence review is required before this answer can be shown to the user.
Review the proposed answer and the actual tool_history structurally.

First classify whether the proposed answer depends on current, changing, or time-sensitive external facts. Examples include current prices, valuation metrics, exchange rates, weather, live status, current officeholders, recent releases, policies, schedules, availability, or other facts whose value can change over time. Do not classify from keyword matching; judge the meaning of the requested claim.

Rules:
- If the proposed answer needs current/time-sensitive external evidence and adequate evidence is not yet in tool_history, return tool_calls for the suitable exposed external tool(s). Do not return a final answer yet.
- If the proposed answer needs current/time-sensitive external evidence and adequate successful external tool results are already in tool_history, return the grounded final answer with final_answer_kind="tool_completion" and put only the successful external evidence tool names in completion_tools.
- If the proposed answer does not need current/time-sensitive external evidence, return the grounded final answer with final_answer_kind="answer" and an empty completion_tools list.
- Never treat automatic memory, recall_memory, prior assistant utterances, or unsupported model knowledge as current external evidence.
- Every externally sourced factual statement in the final answer must be directly supported by the selected evidence.
- A `search_snippet` supports only what its title/snippet explicitly says. Do not infer an author, publication date, plot, product detail, or other attribute that is absent from it.
- `page_evidence` may support facts that are explicit in its matched sections/excerpt.
- Do not fill missing facts from memory or invent plausible titles, authors, dates, plots, prices, ratios, or verification status.
- If available web evidence does not support enough of the user's request, return tool_calls for additional `web_research` instead of a final answer.
- During this review, web evidence IDs may be used in completion_tools only when selecting specific web evidence. The wrapper will validate those IDs against actual tool_history.
""".strip()


class EvidenceGroundingChatModel:
    """Require a structured evidence/freshness review before every final answer.

    Semantic classification is delegated to the model instead of keyword routing in
    framework code. The wrapper validates only structural contracts against actual
    tool history: requested tool calls are executed by the orchestrator, web evidence
    IDs must exist, and declared completion tools must have succeeded.
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
        if turn.tool_calls or not turn.final_answer or turn.final_answer_kind == "blocked":
            return turn

        catalog = web_evidence_catalog(tool_history)
        review_history = [
            *tool_history,
            {
                "tool": "evidence_grounding_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": "final_evidence_review_required",
                    "message": _GROUNDING_REVIEW_INSTRUCTION,
                    "proposed_final_answer": turn.final_answer,
                    "available_web_evidence": compact_evidence_catalog(tool_history),
                    "successful_tools": _successful_tool_names(tool_history),
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

        if reviewed.final_answer_kind == "answer" and not reviewed.completion_tools:
            return ModelTurn(
                final_answer=reviewed.final_answer,
                final_answer_kind="answer",
                completion_tools=[],
            )

        selected = [item for item in reviewed.completion_tools if item]
        if reviewed.final_answer_kind != "tool_completion" or not selected:
            return _blocked_review_turn()

        if catalog and all(evidence_id in catalog for evidence_id in selected):
            return ModelTurn(
                final_answer=reviewed.final_answer,
                final_answer_kind="answer",
                completion_tools=[],
            )

        successful_tools = set(_successful_tool_names(tool_history))
        if all(tool_name in successful_tools for tool_name in selected):
            return ModelTurn(
                final_answer=reviewed.final_answer,
                final_answer_kind="tool_completion",
                completion_tools=selected,
            )

        return _blocked_review_turn()


def _successful_tool_names(tool_history: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for event in tool_history:
        tool_name = str(event.get("tool") or "").strip()
        if not tool_name or tool_name in seen:
            continue
        result = event.get("result")
        if isinstance(result, dict):
            if result.get("ok") is False:
                continue
            if "returncode" in result and result.get("returncode") != 0:
                continue
        seen.add(tool_name)
        names.append(tool_name)
    return names


def _blocked_review_turn() -> ModelTurn:
    return ModelTurn(
        final_answer=(
            "최종 답변에 필요한 최신 외부 근거를 실제 도구 결과와 연결하지 못해 "
            "답변을 확정하지 않았습니다."
        ),
        final_answer_kind="blocked",
    )
