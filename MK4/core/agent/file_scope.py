from __future__ import annotations

import re
from typing import Any

from ...tools.tool_runtime import ToolCall


_BROAD_CHANGE_PATTERNS = (
    re.compile(r"(?:전체|전부|전면|통째|대대적|리팩터|재작성|다시\s*작성|구조\s*개편)"),
    re.compile(r"\b(?:whole|entire|rewrite|refactor|redesign|restructure)\b", re.IGNORECASE),
)

_LOCAL_CHANGE_PATTERNS = (
    re.compile(r"(?:만|해당|이\s*부분|저\s*부분|요소|버튼|select|selector|참조|관련\s*코드|제거|삭제|없애)", re.IGNORECASE),
    re.compile(r"\b(?:only|specific|just|remove|delete|selector|element|reference)\b", re.IGNORECASE),
)

_SCOPE_LIMIT_PATTERNS = (
    re.compile(r"(?:다른|나머지).{0,20}(?:건드리지|수정하지|바꾸지|변경하지)"),
    re.compile(r"\b(?:do not|don't)\b.{0,30}\b(?:touch|modify|change)\b", re.IGNORECASE),
)

_CODE_ANCHOR_RE = re.compile(
    r"`([^`\n]{2,120})`|(?:id|class)=[\"']([^\"']{2,120})[\"']",
    re.IGNORECASE,
)

_GENERIC_ANCHORS = {
    "html", "css", "javascript", "typescript", "python", "code", "file", "select",
    "selector", "element", "button", "script", "style", "model", "remove", "delete",
    "update", "change", "modify", "reference",
}

_DOCUMENT_STRUCTURE_TAGS = (
    "html", "head", "body", "style", "script",
)


def _text(value: Any) -> str:
    return str(value or "").replace("\\", "/")


def _is_broad_request(message: str) -> bool:
    return any(pattern.search(message) for pattern in _BROAD_CHANGE_PATTERNS)


def _is_local_request(message: str) -> bool:
    return any(pattern.search(message) for pattern in _LOCAL_CHANGE_PATTERNS)


def _has_scope_limit(message: str) -> bool:
    return any(pattern.search(message) for pattern in _SCOPE_LIMIT_PATTERNS)


def _request_anchors(message: str) -> set[str]:
    anchors: set[str] = set()
    for match in _CODE_ANCHOR_RE.finditer(message):
        raw = next((group for group in match.groups() if group), "")
        for token in re.findall(r"[A-Za-z0-9_$.-]{3,}", raw.lower()):
            cleaned = token.lstrip("#.")
            if cleaned not in _GENERIC_ANCHORS:
                anchors.add(cleaned)
    for token in re.findall(r"[#.]?[A-Za-z][A-Za-z0-9_-]{3,}", message.lower()):
        cleaned = token.lstrip("#.")
        if cleaned not in _GENERIC_ANCHORS:
            anchors.add(cleaned)
    return anchors


def _changed_line_count(old: str, new: str) -> int:
    old_lines = old.splitlines() or ([old] if old else [])
    new_lines = new.splitlines() or ([new] if new else [])
    return max(len(old_lines), len(new_lines))


def _tag_counts(text: str) -> dict[str, tuple[int, int]]:
    lowered = text.lower()
    return {
        tag: (
            len(re.findall(rf"<{tag}(?:\s|>)", lowered)),
            len(re.findall(rf"</{tag}\s*>", lowered)),
        )
        for tag in _DOCUMENT_STRUCTURE_TAGS
    }


def _structure_swaps(old: str, new: str) -> list[str]:
    old_counts = _tag_counts(old)
    new_counts = _tag_counts(new)
    changed = [tag for tag in _DOCUMENT_STRUCTURE_TAGS if old_counts[tag] != new_counts[tag]]
    if not changed:
        return []
    # A local request may legitimately remove a small element, but changing document-level
    # structure tags is high-risk. The classic failure this catches is <style> -> <script>.
    return changed


def _has_prior_read(tool_history: list[dict], path: str) -> bool:
    normalized = _text(path).strip()
    for event in reversed(tool_history):
        if event.get("tool") != "file_read":
            continue
        result = event.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        if _text(result.get("path")).strip() == normalized:
            return True
    return False


def file_mutation_scope_guard_result(
    *,
    user_message: str,
    call: ToolCall,
    tool_history: list[dict],
) -> dict | None:
    """Block obviously out-of-scope file updates before they touch disk.

    The guard is intentionally narrow: it catches destructive/broad edits with strong evidence
    of scope drift, while leaving normal local edits alone.
    """
    if call.tool != "file_update":
        return None

    args = call.arguments if isinstance(call.arguments, dict) else {}
    path = _text(args.get("path")).strip()
    message = _text(user_message)
    broad_request = _is_broad_request(message)
    local_request = _is_local_request(message)
    scope_limited = _has_scope_limit(message)

    if broad_request:
        return None

    # Full overwrite for a local task is too risky. For non-local requests, at least require
    # the exact file to have been read first.
    if "content" in args and "old" not in args:
        if local_request or scope_limited:
            return {
                "ok": False,
                "error": "file_update_scope_too_broad",
                "message": (
                    "The user requested a local/specific change, but file_update attempted a full-file overwrite. "
                    "Do not rewrite the whole file. Read the exact surrounding lines and use an old/new replacement "
                    "that changes only the requested area."
                ),
                "path": path,
                "recovery": {"next_tools": ["file_read", "file_text_search", "file_update"]},
            }
        if path and not _has_prior_read(tool_history, path):
            return {
                "ok": False,
                "error": "file_overwrite_without_prior_read",
                "message": (
                    "A full-file overwrite was attempted before the exact target file was successfully read. "
                    "Read it first, then prefer a minimal old/new replacement unless a full rewrite was explicitly requested."
                ),
                "path": path,
                "recovery": {"next_tools": ["file_read", "file_update"]},
            }
        return None

    if "old" not in args or "new" not in args:
        return None

    old = _text(args.get("old"))
    new = _text(args.get("new"))

    structural_changes = _structure_swaps(old, new)
    if structural_changes and (local_request or scope_limited):
        return {
            "ok": False,
            "error": "file_update_unrelated_structure_change",
            "message": (
                "This local edit changes document-level structure tags "
                f"({', '.join(structural_changes)}). That is outside the requested scope unless the user explicitly asked for it. "
                "Do not change <style>, <script>, <head>, <body>, or <html> structure while performing a small UI/code edit. "
                "Re-read the exact target block and retry with a smaller replacement."
            ),
            "path": path,
            "recovery": {"next_tools": ["file_read", "file_text_search", "file_update"]},
        }

    change_lines = _changed_line_count(old, new)
    if (local_request or scope_limited) and change_lines > 80:
        return {
            "ok": False,
            "error": "file_update_scope_too_broad",
            "message": (
                f"This local request attempted an old/new replacement spanning about {change_lines} lines. "
                "Use a smaller exact replacement around the requested element or reference instead of changing a large region."
            ),
            "path": path,
            "recovery": {"next_tools": ["file_read", "file_text_search", "file_update"]},
        }

    anchors = _request_anchors(message)
    if anchors and (local_request or scope_limited):
        changed_text = f"{old}\n{new}".lower()
        if not any(anchor in changed_text for anchor in anchors):
            return {
                "ok": False,
                "error": "file_update_missing_request_anchor",
                "message": (
                    "The proposed file_update does not contain any concrete identifier mentioned in the user's request. "
                    f"Expected the changed block to relate to one of: {', '.join(sorted(anchors)[:8])}. "
                    "Search/read the exact target first and make a minimal edit around that identifier."
                ),
                "path": path,
                "recovery": {"next_tools": ["file_text_search", "file_read", "file_update"]},
            }

    return None
