from __future__ import annotations

from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolDefinition
from .web_grounding import compact_evidence_catalog


_EXTERNAL_EVIDENCE_TOOLS = {
    "internet_search",
    "latest_search",
    "web_page_read",
    "web_research",
    "market_snapshot",
}


_GROUNDING_REVIEW_INSTRUCTION = """
Review the proposed response before it is shown to the user.

Freshness rule:
- Inspect every factual assertion in the proposed response, including examples and asides.
- A fact is freshness-sensitive when its value or state could reasonably differ today from yesterday.
- If even one freshness-sensitive fact appears, it must be refreshed from a successful current-turn external data/search tool result.
- Old automatic memory, recall_memory, prior assistant replies, previous-turn tool results, and model knowledge may help identify what to check, but they are not current evidence.
- Stable definitions, mathematical explanations, general domain knowledge, and fixed historical facts do not need fresh evidence.

Evidence rule:
- If current external evidence is missing or insufficient for any freshness-sensitive assertion, call an appropriate read-only external tool now. Do not answer yet.
- If the available current-turn evidence is sufficient, return the corrected grounded response.
- If no freshness-sensitive assertion exists, return the response normally.
- Do not invent unsupported values or silently fill gaps from memory.

Tool use during this review is exploratory. When current evidence may help, prefer checking over guessing.
""".strip()


class EvidenceGroundingChatModel:
    """Review draft answers while keeping the main model action contract lightweight."""

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
        if turn.tool_calls or not turn.final_answer:
            return turn

        review_history = [
            *tool_history,
            {
                "tool": "evidence_grounding_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": "final_evidence_review_required",
                    "message": _GROUNDING_REVIEW_INSTRUCTION,
                    "proposed_response": turn.final_answer,
                    "available_web_evidence": compact_evidence_catalog(tool_history),
                    "successful_external_tools": _successful_external_tool_names(tool_history),
                },
            },
        ]
        reviewed = await self._delegate.next_turn(
            system=f"{system}\n\n{_GROUNDING_REVIEW_INSTRUCTION}",
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=review_history,
        )
        if reviewed.tool_calls or not reviewed.final_answer:
            return reviewed

        supporting_tools = _successful_external_tool_names(tool_history)
        if supporting_tools:
            return ModelTurn(
                final_answer=reviewed.final_answer,
                final_answer_kind="tool_completion",
                completion_tools=supporting_tools,
            )
        return ModelTurn(final_answer=reviewed.final_answer)


def _successful_external_tool_names(tool_history: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for event in tool_history:
        tool_name = str(event.get("tool") or "").strip()
        if tool_name not in _EXTERNAL_EVIDENCE_TOOLS or tool_name in seen:
            continue
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("ok") is False:
            continue
        if "returncode" in result and result.get("returncode") != 0:
            continue
        seen.add(tool_name)
        names.append(tool_name)
    return names
