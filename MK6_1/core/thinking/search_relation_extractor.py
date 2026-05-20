from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from ...tools.ollama_client import chat as llm_chat
from ...tools.search_client import SearchResult


ConnectType = Literal["flow", "neutral", "opposite", "conflict"]
_ALLOWED_CONNECT_TYPES: set[str] = {"flow", "neutral", "opposite", "conflict"}
_MAX_EVIDENCE_LEN = 280
_MAX_SNIPPET_LEN = 420
_MAX_SEARCH_ITEMS = 12


@dataclass(frozen=True, slots=True)
class RelationCandidate:
    subject: str
    predicate: str
    object: str
    connect_type: ConnectType
    confidence: float
    evidence: str
    source_title: str | None = None
    source_url: str | None = None


async def extract_relation_candidates(
    *,
    user_input: str | None,
    query: str,
    search_results: list[SearchResult],
    seed_concepts: list[str],
    model: str | None = None,
    llm_chat_fn: Callable[[str, str, str | None], Awaitable[str]] = llm_chat,
) -> list[RelationCandidate]:
    if not search_results:
        return []

    sources = []
    for item in search_results[:_MAX_SEARCH_ITEMS]:
        sources.append({
            "source": item.source,
            "title": item.title,
            "url": item.url,
            "snippet": item.snippet[:_MAX_SNIPPET_LEN],
            "rank": item.rank,
        })

    payload = {
        "query": query,
        "user_input": user_input or "",
        "seed_concepts": seed_concepts,
        "sources": sources,
        "output_schema": {
            "relations": [
                {
                    "subject": "string",
                    "predicate": "string",
                    "object": "string",
                    "connect_type": "flow|neutral|opposite|conflict",
                    "confidence": "float_0_to_1",
                    "evidence": "string",
                    "source_title": "string_or_null",
                    "source_url": "string_or_null",
                }
            ]
        },
    }

    system_prompt = (
        "You extract graph relation candidates from search evidence. "
        "Return JSON only. Do not output any text outside JSON."
    )
    user_prompt = (
        "Task:\n"
        "1. Extract only relations grounded in the provided sources.\n"
        "2. Do not invent facts that are not in sources.\n"
        "3. Include operational, descriptive, causal, taxonomy, part-whole, and mechanism relations.\n"
        "4. Do not perform response policy decisions.\n"
        "5. connect_type must be one of flow, neutral, opposite, conflict.\n"
        "6. confidence must be in [0,1].\n"
        "7. evidence must be a short citation-like summary.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )

    raw = await llm_chat_fn(system_prompt, user_prompt, model)
    parsed = _parse_json(raw)
    return _validate_relations(parsed)


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if not text:
        raise RuntimeError("search relation extractor returned empty response")

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        extracted = _extract_json_object_text(text)
        if extracted is None:
            preview = text[:240].replace("\n", "\\n")
            raise RuntimeError(
                f"search relation extractor JSON parse failed: {exc}; raw_preview={preview!r}"
            ) from exc
        try:
            value = json.loads(extracted)
        except json.JSONDecodeError as inner_exc:
            preview = extracted[:240].replace("\n", "\\n")
            raise RuntimeError(
                f"search relation extractor JSON parse failed after extraction: {inner_exc}; "
                f"extracted_preview={preview!r}"
            ) from inner_exc
    if not isinstance(value, dict):
        raise RuntimeError("search relation extractor JSON root must be an object")
    return value


def _extract_json_object_text(text: str) -> str | None:
    fenced = _extract_fenced_json(text)
    if fenced is not None:
        return fenced
    return _extract_balanced_object(text)


def _extract_fenced_json(text: str) -> str | None:
    fence = "```"
    pos = 0
    while True:
        start = text.find(fence, pos)
        if start < 0:
            return None
        header_end = text.find("\n", start + len(fence))
        if header_end < 0:
            return None
        lang = text[start + len(fence):header_end].strip().lower()
        end = text.find(fence, header_end + 1)
        if end < 0:
            return None
        body = text[header_end + 1:end].strip()
        if lang in {"json", ""} and body.startswith("{") and body.endswith("}"):
            return body
        pos = end + len(fence)


def _extract_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return None


def _validate_relations(payload: dict) -> list[RelationCandidate]:
    relations = payload.get("relations")
    if relations is None:
        raise RuntimeError("search relation extractor output missing 'relations'")
    if not isinstance(relations, list):
        raise RuntimeError("search relation extractor 'relations' must be a list")

    candidates: list[RelationCandidate] = []
    for idx, item in enumerate(relations):
        if not isinstance(item, dict):
            raise RuntimeError(f"relation[{idx}] must be an object")

        subject = _required_text(item, "subject", idx)
        predicate = _required_text(item, "predicate", idx)
        obj = _required_text(item, "object", idx)
        connect_type = _required_text(item, "connect_type", idx)
        if connect_type not in _ALLOWED_CONNECT_TYPES:
            raise RuntimeError(f"relation[{idx}].connect_type invalid: {connect_type!r}")

        confidence_raw = item.get("confidence")
        if not isinstance(confidence_raw, (int, float)):
            raise RuntimeError(f"relation[{idx}].confidence must be number")
        confidence = float(confidence_raw)
        if not (0.0 <= confidence <= 1.0):
            raise RuntimeError(f"relation[{idx}].confidence out of range: {confidence}")

        evidence = _required_text(item, "evidence", idx)
        source_title = _optional_text(item.get("source_title"))
        source_url = _optional_text(item.get("source_url"))

        candidates.append(RelationCandidate(
            subject=subject,
            predicate=predicate,
            object=obj,
            connect_type=connect_type,  # type: ignore[arg-type]
            confidence=confidence,
            evidence=evidence[:_MAX_EVIDENCE_LEN],
            source_title=source_title,
            source_url=source_url,
        ))
    return candidates


def _required_text(item: dict, field: str, idx: int) -> str:
    value = item.get(field)
    if not isinstance(value, str):
        raise RuntimeError(f"relation[{idx}].{field} must be string")
    text = value.strip()
    if not text:
        raise RuntimeError(f"relation[{idx}].{field} must not be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("optional source field must be string or null")
    text = value.strip()
    return text or None
