from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .llm_client import ChatModel, ModelRequestError, ModelTurn
from .ollama_client import chat as ollama_chat
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
Review whether the proposed response is grounded in the evidence already available in this turn.

This is a judgment-only review. You cannot call tools and must not choose a tool. If evidence is missing, report only the missing factual aspects that must be resolved before release.

Freshness rule:
- Inspect every factual assertion in the proposed response, including examples and asides.
- A fact is freshness-sensitive when its value or state could reasonably differ today from yesterday.
- Every freshness-sensitive assertion must be supported by successful current-turn external data/search evidence.
- Old automatic memory, recall_memory, prior assistant replies, previous-turn tool results, and model knowledge may help identify what needs checking, but they are not current evidence.
- Stable definitions, mathematical explanations, general domain knowledge, and fixed historical facts do not need fresh external evidence.

Evidence rule:
- Judge only the supplied proposed response and current-turn evidence.
- Do not request or select a specific tool.
- If the evidence is insufficient, set grounded=false and describe the unresolved factual aspects in missing_aspects.
- If the evidence is sufficient, set grounded=true, keep missing_aspects empty, and return a corrected_response that stays within what the evidence supports.
- If no freshness-sensitive assertion exists, grounded may be true without external evidence.
- Do not invent unsupported values or silently fill gaps from memory.
""".strip()

_GROUNDING_RETRY_INSTRUCTION = """
The proposed response failed final evidence grounding. The grounding reviewer cannot call tools and identified unresolved factual aspects in the latest evidence_grounding_guard result.
Resolve those missing aspects using the exposed tools when needed, then produce a new answer. Choose tools from the actual missing information; do not repeat a successful search merely because a grounding review occurred.
""".strip()


@dataclass(frozen=True, slots=True)
class GroundingReview:
    grounded: bool
    missing_aspects: tuple[str, ...] = ()
    corrected_response: str | None = None


class EvidenceGroundingChatModel:
    """Review draft answers without granting the grounding reviewer tool-calling authority."""

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

        review = await review_final_grounding(
            system=system,
            user_message=user_message,
            proposed_response=turn.final_answer,
            model=model,
            tool_history=tool_history,
        )
        if review.grounded:
            supporting_tools = _successful_external_tool_names(tool_history)
            if supporting_tools:
                return ModelTurn(
                    final_answer=review.corrected_response,
                    final_answer_kind="tool_completion",
                    completion_tools=supporting_tools,
                )
            return ModelTurn(final_answer=review.corrected_response)

        review_history = [
            *tool_history,
            {
                "tool": "evidence_grounding_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": "final_evidence_insufficient",
                    "message": _GROUNDING_RETRY_INSTRUCTION,
                    "missing_aspects": list(review.missing_aspects),
                    "proposed_response": turn.final_answer,
                    "available_web_evidence": compact_evidence_catalog(tool_history),
                    "successful_external_tools": _successful_external_tool_names(tool_history),
                },
            },
        ]
        return await self._delegate.next_turn(
            system=f"{system}\n\n{_GROUNDING_RETRY_INSTRUCTION}",
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=review_history,
        )


async def review_final_grounding(
    *,
    system: str,
    user_message: str,
    proposed_response: str,
    model: str | None,
    tool_history: list[dict[str, Any]],
) -> GroundingReview:
    response_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "grounded": {"type": "boolean"},
            "missing_aspects": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
            },
            "corrected_response": {"type": ["string", "null"]},
        },
        "required": ["grounded", "missing_aspects", "corrected_response"],
        "additionalProperties": False,
    }
    payload = {
        "user_request": user_message,
        "proposed_response": proposed_response,
        "available_web_evidence": compact_evidence_catalog(tool_history),
        "successful_external_tools": _successful_external_tool_names(tool_history),
    }
    try:
        raw = await ollama_chat(
            system=f"{system}\n\n{_GROUNDING_REVIEW_INSTRUCTION}",
            user=json.dumps(payload, ensure_ascii=False),
            model=model,
            response_format=response_schema,
        )
    except ValueError as exc:
        raise ModelRequestError(str(exc)) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Final grounding review must be valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("grounded"), bool):
        raise RuntimeError("Final grounding review must contain boolean grounded.")
    missing = data.get("missing_aspects")
    if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
        raise RuntimeError("Final grounding review missing_aspects must be a list of strings.")
    cleaned_missing = tuple(dict.fromkeys(item.strip() for item in missing if item.strip()))
    corrected = data.get("corrected_response")
    if corrected is not None and not isinstance(corrected, str):
        raise RuntimeError("Final grounding review corrected_response must be string or null.")
    cleaned_corrected = corrected.strip() if isinstance(corrected, str) else None

    if data["grounded"]:
        if cleaned_missing:
            raise RuntimeError("Grounded final review must not contain missing_aspects.")
        if not cleaned_corrected:
            raise RuntimeError("Grounded final review must contain corrected_response.")
    else:
        if not cleaned_missing:
            raise RuntimeError("Ungrounded final review must explain at least one missing aspect.")
        if cleaned_corrected:
            raise RuntimeError("Ungrounded final review must not provide corrected_response.")

    return GroundingReview(
        grounded=data["grounded"],
        missing_aspects=cleaned_missing,
        corrected_response=cleaned_corrected,
    )


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
