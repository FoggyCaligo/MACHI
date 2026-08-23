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

Do not keep recovery active merely because more detail, more sources, deeper comparison, broader coverage, newer trends, extra examples, or a better answer could be obtained. Those are optional improvements unless the user explicitly requested them.
Do not add requirements that the user did not ask for.
Do not redefine the user's target, category, scope, or requested output.
If the three conditions above are satisfied, mark adequate=true and return an empty missing_aspects list.
If adequate=false, missing_aspects must identify only the concrete defect that prevents one of the three conditions above from being satisfied.
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
            "missing_aspects": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
            },
        },
        "required": ["adequate", "missing_aspects"],
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
    missing = data.get("missing_aspects")
    if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
        raise RuntimeError("Tool result adequacy review missing_aspects must be a list of strings.")
    cleaned = tuple(dict.fromkeys(item.strip() for item in missing if item.strip()))
    if data["adequate"] is False and not cleaned:
        raise RuntimeError("Inadequate tool result review must explain at least one missing aspect.")
    if data["adequate"] is True and cleaned:
        raise RuntimeError("Adequate tool result review must not include missing aspects.")
    return ToolResultAdequacy(adequate=data["adequate"], missing_aspects=cleaned)
