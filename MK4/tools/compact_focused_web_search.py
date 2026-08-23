from __future__ import annotations

import json
import sys
from typing import Any

from .. import config
from .focused_web_search import FocusedWebSearchTool


class CompactFocusedWebSearchTool(FocusedWebSearchTool):
    """Preserve web research evidence while removing structural duplication.

    Search behavior, result ranking, source count and page-read count remain owned by
    FocusedWebSearchTool. This class only reshapes the returned payload after research
    has completed so the model does not reread the same page text through multiple
    fields.
    """

    async def _run_research(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await super()._run_research(arguments)
        before_chars = _payload_chars(result)
        evidence = result.get("evidence")
        if not isinstance(evidence, list):
            return result

        compact_evidence = [
            _deduplicate_evidence_item(item)
            for item in evidence
        ]
        evidence_urls = {
            str(item.get("url") or "")
            for item in compact_evidence
            if isinstance(item, dict) and item.get("url")
        }

        search_results = result.get("results")
        if isinstance(search_results, list):
            result["results"] = [
                _deduplicate_search_result(item, evidence_urls=evidence_urls)
                for item in search_results
            ]
        result["evidence"] = compact_evidence
        _debug_payload_compaction(before_chars=before_chars, after_chars=_payload_chars(result))
        return result


def _deduplicate_evidence_item(item: object) -> object:
    if not isinstance(item, dict):
        return item

    compact = dict(item)
    matched_raw = item.get("matched_sections")
    matched_sections = (
        [str(section) for section in matched_raw if str(section).strip()]
        if isinstance(matched_raw, list)
        else []
    )
    compact["matched_sections"] = matched_sections

    excerpt = str(item.get("excerpt") or "")
    if not excerpt:
        compact.pop("excerpt", None)
        return compact

    matched_normalized = {_normalize_text(section) for section in matched_sections}
    remainder_lines = [
        line.strip()
        for line in excerpt.splitlines()
        if line.strip() and _normalize_text(line) not in matched_normalized
    ]
    if remainder_lines:
        compact["excerpt_context"] = "\n".join(remainder_lines)
    compact.pop("excerpt", None)
    return compact


def _deduplicate_search_result(item: object, *, evidence_urls: set[str]) -> object:
    if not isinstance(item, dict):
        return item
    url = str(item.get("url") or "")
    if not url or url not in evidence_urls:
        return item

    # The same URL already has richer page evidence. Keep only search-source metadata
    # here instead of repeating its title/snippet/page text a second time.
    return {
        key: item.get(key)
        for key in ("url", "source", "query_node")
        if item.get(key) is not None
    }


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _payload_chars(payload: object) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _debug_payload_compaction(*, before_chars: int, after_chars: int) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    print(
        "[MK4 web] research_payload_chars "
        f"before={before_chars} after={after_chars} saved={max(0, before_chars - after_chars)}",
        file=sys.stderr,
        flush=True,
    )
