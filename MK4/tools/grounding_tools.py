from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import json
from time import perf_counter
from typing import Any

from .debug_timing import log_timing
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
Review the proposed response on three axes before it may be released:
1. factual grounding in the evidence already available in this turn,
2. freshness grounding for facts whose value or state can change,
3. task alignment: whether the response actually answers the user's current request in its conversational context.

This is a judgment-only review. You cannot call tools, choose a tool, or rewrite the answer. If release should be blocked, report only the unresolved aspects that must be fixed before release.

Task-alignment rule:
- Read the current request in the supplied conversational context. Resolve omitted subjects, references, constraints, and continuation meaning from that context when needed.
- Identify the actual outcomes the user asked for. Check whether the proposed response directly addresses those outcomes instead of answering a nearby, substituted, broader, narrower, or differently interpreted question.
- Do not add requirements the user did not ask for. Optional personalization, extra examples, or greater comprehensiveness are not alignment requirements.
- A response can be factually grounded and still be task_aligned=false if it answers the wrong question, omits a requested outcome, or changes the requested target.
- Prior assistant claims and prior-turn tool results may clarify conversational meaning, but they are not current evidence.

Freshness rule:
- Inspect every factual assertion in the proposed response, including examples and asides.
- A fact is freshness-sensitive when its value or state could reasonably differ today from yesterday.
- Every freshness-sensitive assertion must be supported by successful current-turn external data/search evidence.
- Old automatic memory, recall_memory, prior assistant replies, previous-turn tool results, and model knowledge may help identify what needs checking, but they are not current evidence.
- Stable definitions, mathematical explanations, general domain knowledge, and fixed historical facts do not need fresh external evidence.

Evidence rule:
- Judge only the supplied proposed response and current-turn evidence.
- Do not request or select a specific tool.
- Do not rewrite or improve the proposed response.
- If factual evidence is insufficient, set grounded=false.
- If the response does not answer the actual request, set task_aligned=false.
- If both checks pass, set grounded=true and task_aligned=true and keep missing_aspects empty.
- If either check fails, describe the concrete unresolved or misaligned aspects in missing_aspects.
- If no freshness-sensitive assertion exists, grounded may be true without external evidence.
- Do not invent unsupported values or silently fill gaps from memory.
""".strip()

_GROUNDING_RETRY_INSTRUCTION = """
The proposed response failed final grounding or task-alignment review. The reviewer cannot call tools and identified unresolved aspects in the latest evidence_grounding_guard result.
Fix the actual problem before producing a new answer: use exposed tools when evidence is missing, or correct the interpretation/coverage when the response did not answer the user's actual request. Do not repeat a successful search merely because a review occurred.
""".strip()


@dataclass(frozen=True, slots=True)
class GroundingReview:
    grounded: bool
    task_aligned: bool = True
    missing_aspects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PrecomputedGroundingReview:
    proposed_response: str
    review: GroundingReview


_PRECOMPUTED_GROUNDING: ContextVar[_PrecomputedGroundingReview | None] = ContextVar(
    "mk4_precomputed_grounding_review",
    default=None,
)


def start_grounding_review_scope() -> Token[_PrecomputedGroundingReview | None]:
    return _PRECOMPUTED_GROUNDING.set(None)


def reset_grounding_review_scope(token: Token[_PrecomputedGroundingReview | None]) -> None:
    _PRECOMPUTED_GROUNDING.reset(token)


def store_precomputed_grounding_review(*, proposed_response: str, review: GroundingReview) -> None:
    _PRECOMPUTED_GROUNDING.set(
        _PrecomputedGroundingReview(proposed_response=proposed_response, review=review)
    )


def take_precomputed_grounding_review(*, proposed_response: str) -> GroundingReview | None:
    pending = _PRECOMPUTED_GROUNDING.get()
    _PRECOMPUTED_GROUNDING.set(None)
    if pending is None or pending.proposed_response != proposed_response:
        return None
    return pending.review


class EvidenceGroundingChatModel:
    """Review draft answers without granting the reviewer tool-calling authority."""

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

        review = take_precomputed_grounding_review(proposed_response=turn.final_answer)
        if review is None:
            review = await review_final_grounding(
                system=system,
                user_message=user_message,
                proposed_response=turn.final_answer,
                model=model,
                tool_history=tool_history,
            )
        if review.grounded and review.task_aligned:
            return _release_grounded_turn(turn, tool_history=tool_history)

        review_history = [
            *tool_history,
            {
                "tool": "evidence_grounding_guard",
                "arguments": {},
                "result": {
                    "ok": False,
                    "error": "final_grounding_or_alignment_failed",
                    "message": _GROUNDING_RETRY_INSTRUCTION,
                    "grounded": review.grounded,
                    "task_aligned": review.task_aligned,
                    "missing_aspects": list(review.missing_aspects),
                    "proposed_response": turn.final_answer,
                    "available_web_evidence": compact_evidence_catalog(tool_history),
                    "successful_external_tools": _successful_external_tool_names(tool_history),
                },
            },
        ]
        retry = await self._delegate.next_turn(
            system=f"{system}\n\n{_GROUNDING_RETRY_INSTRUCTION}",
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=review_history,
        )
        if retry.tool_calls or not retry.final_answer:
            return retry

        retry_review = take_precomputed_grounding_review(proposed_response=retry.final_answer)
        if retry_review is None:
            return retry
        if retry_review.grounded and retry_review.task_aligned:
            return _release_grounded_turn(retry, tool_history=tool_history)
        return ModelTurn(
            final_answer="최종 근거 및 요청 정합성 검증을 통과하지 못해 답변을 확정하지 않았습니다.",
            final_answer_kind="blocked",
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
            "task_aligned": {"type": "boolean"},
            "missing_aspects": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
            },
        },
        "required": ["grounded", "task_aligned", "missing_aspects"],
        "additionalProperties": False,
    }
    payload = {
        "user_request": user_message,
        "proposed_response": proposed_response,
        "available_web_evidence": compact_evidence_catalog(tool_history),
        "successful_external_tools": _successful_external_tool_names(tool_history),
    }
    started = perf_counter()
    try:
        try:
            raw = await ollama_chat(
                system=f"{system}\n\n{_GROUNDING_REVIEW_INSTRUCTION}",
                user=json.dumps(payload, ensure_ascii=False),
                model=model,
                response_format=response_schema,
            )
        except ValueError as exc:
            raise ModelRequestError(str(exc)) from exc
    finally:
        log_timing("grounding_review", perf_counter() - started)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Final grounding review must be valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("grounded"), bool):
        raise RuntimeError("Final grounding review must contain boolean grounded.")
    if not isinstance(data.get("task_aligned"), bool):
        raise RuntimeError("Final grounding review must contain boolean task_aligned.")
    missing = data.get("missing_aspects")
    if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
        raise RuntimeError("Final grounding review missing_aspects must be a list of strings.")
    cleaned_missing = tuple(dict.fromkeys(item.strip() for item in missing if item.strip()))

    if data["grounded"] and data["task_aligned"] and cleaned_missing:
        raise RuntimeError("Passing final review must not contain missing_aspects.")
    if (data["grounded"] is False or data["task_aligned"] is False) and not cleaned_missing:
        raise RuntimeError("Failed final review must explain at least one missing aspect.")

    return GroundingReview(
        grounded=data["grounded"],
        task_aligned=data["task_aligned"],
        missing_aspects=cleaned_missing,
    )


def _release_grounded_turn(turn: ModelTurn, *, tool_history: list[dict[str, Any]]) -> ModelTurn:
    supporting_tools = _successful_external_tool_names(tool_history)
    if not supporting_tools:
        return turn
    return ModelTurn(
        final_answer=turn.final_answer,
        final_answer_kind="tool_completion",
        completion_tools=supporting_tools,
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
