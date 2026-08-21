from __future__ import annotations

from typing import Any


WEB_EVIDENCE_TOOLS = frozenset({
    "internet_search",
    "latest_search",
    "web_page_read",
    "web_research",
})


def web_evidence_id(event_index: int, kind: str, item_index: int | None = None) -> str:
    if item_index is None:
        return f"web:{event_index}:{kind}"
    return f"web:{event_index}:{kind}:{item_index}"


def web_evidence_catalog(tool_history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the exact web evidence items available to the model.

    IDs are derived only from tool-history position and result structure. No text
    matching, entity guessing, or semantic heuristics are used.
    """
    catalog: dict[str, dict[str, Any]] = {}
    for event_index, event in enumerate(tool_history):
        tool = str(event.get("tool") or "")
        if tool not in WEB_EVIDENCE_TOOLS:
            continue
        result = event.get("result")
        if not isinstance(result, dict) or result.get("ok") is False:
            continue

        if tool == "web_research":
            evidence = result.get("evidence")
            if isinstance(evidence, list) and evidence:
                for item_index, item in enumerate(evidence):
                    if not isinstance(item, dict):
                        continue
                    evidence_id = web_evidence_id(event_index, "evidence", item_index)
                    catalog[evidence_id] = {
                        "evidence_id": evidence_id,
                        "tool": tool,
                        "scope": "page_evidence",
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "query_node": item.get("query_node"),
                        "matched_sections": item.get("matched_sections"),
                        "excerpt": item.get("excerpt"),
                    }
                continue

        if tool in {"internet_search", "latest_search", "web_research"}:
            results = result.get("results")
            if isinstance(results, list):
                for item_index, item in enumerate(results):
                    if not isinstance(item, dict):
                        continue
                    evidence_id = web_evidence_id(event_index, "result", item_index)
                    catalog[evidence_id] = {
                        "evidence_id": evidence_id,
                        "tool": tool,
                        "scope": "search_snippet",
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "snippet": item.get("snippet"),
                        "source": item.get("source"),
                        "query_node": item.get("query_node"),
                    }
            continue

        if tool == "web_page_read":
            evidence_id = web_evidence_id(event_index, "page")
            catalog[evidence_id] = {
                "evidence_id": evidence_id,
                "tool": tool,
                "scope": "page_evidence",
                "title": result.get("title"),
                "url": result.get("url"),
                "matched_sections": result.get("matched_sections"),
                "content": result.get("content"),
            }
    return catalog


def compact_evidence_catalog(tool_history: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    items = list(web_evidence_catalog(tool_history).values())[: max(0, limit)]
    compact: list[dict[str, Any]] = []
    for item in items:
        compact.append({
            key: item.get(key)
            for key in (
                "evidence_id",
                "tool",
                "scope",
                "title",
                "url",
                "snippet",
                "matched_sections",
                "excerpt",
            )
            if item.get(key) not in (None, "", [])
        })
    return compact
