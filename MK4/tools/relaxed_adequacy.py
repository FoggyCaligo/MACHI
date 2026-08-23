from __future__ import annotations

import json
from time import perf_counter

from .debug_timing import log_timing
from .llm_client import ModelRequestError
from .ollama_client import chat as ollama_chat
from .tool_requirements import (
    FrozenToolRequirements,
    ToolResultAdequacy,
    _successful_tool_result_payloads,
)


_RELAXED_RESULT_ADEQUACY_INSTRUCTION = """
Review whether the successful tool results are good enough to answer the user's actual request now.
This is a release gate, not a quality-improvement checklist.

Mark adequate=true when all of these are true:
1. The successful evidence does not contain a material error that would make the answer wrong.
2. If the request depends on information that could reasonably differ today from yesterday, the evidence is current enough for the requested time.
3. The evidence is sufficient to answer what the user actually asked for.

Do not keep recovery active merely because more detail, more sources, deeper comparison, broader coverage, newer trends, extra examples, personalization, preference information, or a better answer could be obtained. Those are optional improvements unless the user explicitly requested them.
Do not add requirements that the user did not ask for. Do not require budget, taste, preferences, dimensions, style, or other personalization inputs unless the user's request explicitly made them necessary constraints.
Do not redefine the user's target, category, scope, or requested output.

If adequate=false, every blocking_defect must pair:
- requested_aspect: an outcome or constraint that is actually present in the user's request; and
- evidence_defect: the concrete problem in the successful evidence that prevents that requested aspect from being answered correctly now.

A missing user preference is not an evidence defect unless the user explicitly required the recommendation to satisfy that preference. If no concrete evidence defect blocks an actually requested aspect, mark adequate=true.
Use semantic judgment, not keyword matching or tool-name-specific rules.
""".strip()


async def review_relaxed_tool_result_adequacy(
    *,
    system: str,
    user_message: str,
    model: str | None,
    requirements: FrozenToolRequirements,
    tool_history: list[dict],
) -> ToolResultAdequacy:
    response_schema = {
        "type": "object",
        "properties": {
            "adequate": {"type": "boolean"},
            "blocking_defects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requested_aspect": {"type": "string", "minLength": 1},
                        "evidence_defect": {"type": "string", "minLength": 1},
                    },
                    "required": ["requested_aspect", "evidence_defect"],
                    "additionalProperties": False,
                },
                "maxItems": 8,
            },
        },
        "required": ["adequate", "blocking_defects"],
        "additionalProperties": False,
    }
    payload = {
        "user_request": user_message,
        "frozen_required_tools": list(requirements.required_tools),
        "successful_tool_results": _successful_tool_result_payloads(tool_history),
    }
    started = perf_counter()
    try:
        try:
            raw = await ollama_chat(
                system=f"{system}\n\n{_RELAXED_RESULT_ADEQUACY_INSTRUCTION}",
                user=json.dumps(payload, ensure_ascii=False),
                model=model,
                response_format=response_schema,
            )
        except ValueError as exc:
            raise ModelRequestError(str(exc)) from exc
    finally:
        log_timing("adequacy_review", perf_counter() - started)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Tool result adequacy review must be valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("adequate"), bool):
        raise RuntimeError("Tool result adequacy review must contain boolean adequate.")

    defects = data.get("blocking_defects")
    if not isinstance(defects, list):
        raise RuntimeError("Tool result adequacy review blocking_defects must be a list.")

    cleaned_defects: list[tuple[str, str]] = []
    for index, defect in enumerate(defects):
        if not isinstance(defect, dict):
            raise RuntimeError(f"blocking_defects[{index}] must be an object.")
        requested_aspect = defect.get("requested_aspect")
        evidence_defect = defect.get("evidence_defect")
        if not isinstance(requested_aspect, str) or not requested_aspect.strip():
            raise RuntimeError(
                f"blocking_defects[{index}].requested_aspect must be a non-empty string."
            )
        if not isinstance(evidence_defect, str) or not evidence_defect.strip():
            raise RuntimeError(
                f"blocking_defects[{index}].evidence_defect must be a non-empty string."
            )
        pair = (requested_aspect.strip(), evidence_defect.strip())
        if pair not in cleaned_defects:
            cleaned_defects.append(pair)

    if data["adequate"] is False and not cleaned_defects:
        raise RuntimeError(
            "Inadequate tool result review must identify at least one blocking defect."
        )
    if data["adequate"] is True and cleaned_defects:
        raise RuntimeError(
            "Adequate tool result review must not include blocking defects."
        )

    missing_aspects = tuple(
        f"Requested aspect: {requested_aspect}; evidence defect: {evidence_defect}"
        for requested_aspect, evidence_defect in cleaned_defects
    )
    return ToolResultAdequacy(
        adequate=data["adequate"],
        missing_aspects=missing_aspects,
    )
