from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import posixpath
import re
from typing import Any, Awaitable, Callable


ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_FILE_PATH_TOOLS = {
    "file_read",
    "file_create",
    "file_update",
    "file_delete",
    "file_download_link",
    "document_read",
    "image_analyze",
}
_FILE_ROOT_TOOLS = {"file_tree", "file_search", "file_text_search"}
_FILE_RELATED_TOOLS = _FILE_PATH_TOOLS | _FILE_ROOT_TOOLS
_FILE_WORKING_ROOT: ContextVar[str] = ContextVar("file_working_root", default=".")
_FILE_TASK_MESSAGE: ContextVar[str] = ContextVar("file_task_message", default="")
_FILE_TASK_READ_PATHS: ContextVar[frozenset[str]] = ContextVar("file_task_read_paths", default=frozenset())
_WORKSPACE_RELATIVE_BYPASS_PREFIXES = (".mk4_uploads/",)

_BROAD_CHANGE_RE = re.compile(
    r"(?:전체|전부|전면|통째|대대적|리팩터|재작성|다시\s*작성|구조\s*개편)|"
    r"\b(?:whole|entire|rewrite|refactor|redesign|restructure)\b",
    re.IGNORECASE,
)
_LOCAL_CHANGE_RE = re.compile(
    r"(?:만|해당|이\s*부분|저\s*부분|요소|버튼|select|selector|참조|관련\s*코드|제거|삭제|없애)|"
    r"\b(?:only|specific|just|remove|delete|selector|element|reference)\b",
    re.IGNORECASE,
)
_SCOPE_LIMIT_RE = re.compile(
    r"(?:다른|나머지).{0,20}(?:건드리지|수정하지|바꾸지|변경하지)|"
    r"\b(?:do not|don't)\b.{0,30}\b(?:touch|modify|change)\b",
    re.IGNORECASE,
)
_CODE_ANCHOR_RE = re.compile(
    r"`([^`\n]{2,120})`|(?:id|class)=[\"']([^\"']{2,120})[\"']",
    re.IGNORECASE,
)
_BARE_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9])([#.][A-Za-z][A-Za-z0-9_-]{2,}|[A-Za-z][A-Za-z0-9]*[-_][A-Za-z0-9_-]{2,})")
_GENERIC_ANCHORS = {
    "html", "css", "javascript", "typescript", "python", "code", "file", "select",
    "selector", "element", "button", "script", "style", "model", "remove", "delete",
    "update", "change", "modify", "reference",
}
_DOCUMENT_STRUCTURE_TAGS = ("html", "head", "body", "style", "script")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    model_visible: bool = True


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool: str
    arguments: dict[str, Any]


def get_file_working_root() -> str:
    return _FILE_WORKING_ROOT.get()


def set_file_working_root(root: str) -> Token[str]:
    return _FILE_WORKING_ROOT.set(_normalize_root_value(root))


def reset_file_working_root(token: Token[str]) -> None:
    _FILE_WORKING_ROOT.reset(token)


def set_file_task_message(message: str) -> tuple[Token[str], Token[frozenset[str]]]:
    """Start one user request's file-mutation scope context."""
    message_token = _FILE_TASK_MESSAGE.set(str(message or ""))
    reads_token = _FILE_TASK_READ_PATHS.set(frozenset())
    return message_token, reads_token


def reset_file_task_message(tokens: tuple[Token[str], Token[frozenset[str]]]) -> None:
    message_token, reads_token = tokens
    _FILE_TASK_READ_PATHS.reset(reads_token)
    _FILE_TASK_MESSAGE.reset(message_token)


def _normalize_root_value(root: str) -> str:
    value = str(root or ".").strip().replace("\\", "/") or "."
    normalized = posixpath.normpath(value)
    return normalized or "."


def _is_absolute_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))


def _is_workspace_relative_bypass(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in _WORKSPACE_RELATIVE_BYPASS_PREFIXES)


def _resolve_under_working_root(value: str, working_root: str) -> str:
    raw = str(value or "").strip().replace("\\", "/") or "."
    if _is_absolute_path(raw) or _is_workspace_relative_bypass(raw):
        return _normalize_root_value(raw)

    root = _normalize_root_value(working_root)
    if root == ".":
        return _normalize_root_value(raw)
    if raw == root or raw.startswith(root + "/"):
        return _normalize_root_value(raw)
    return _normalize_root_value(posixpath.join(root, raw))


def _normalize_file_call_arguments(call: ToolCall, working_root: str) -> None:
    if call.tool not in _FILE_RELATED_TOOLS:
        return
    arguments = dict(call.arguments)
    if call.tool in _FILE_PATH_TOOLS:
        path = str(arguments.get("path") or "").strip()
        if path:
            arguments["path"] = _resolve_under_working_root(path, working_root)
    else:
        root = str(arguments.get("root") or ".").strip() or "."
        arguments["root"] = _resolve_under_working_root(root, working_root)
    call.arguments.clear()
    call.arguments.update(arguments)


def _maybe_update_working_root(
    *,
    call: ToolCall,
    original_arguments: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if result.get("ok") is not True:
        return

    if call.tool == "file_tree" and "root" in original_arguments:
        resolved_root = str(call.arguments.get("root") or ".").strip() or "."
        _FILE_WORKING_ROOT.set(_normalize_root_value(resolved_root))
        return

    if get_file_working_root() == "." and call.tool in {"file_search", "file_text_search"}:
        candidate = str(original_arguments.get("root") or ".").strip()
        if candidate and candidate != ".":
            resolved_root = str(call.arguments.get("root") or ".").strip() or "."
            _FILE_WORKING_ROOT.set(_normalize_root_value(resolved_root))


def _remember_successful_file_read(call: ToolCall, result: dict[str, Any]) -> None:
    if call.tool != "file_read" or result.get("ok") is not True:
        return
    path = str(result.get("path") or call.arguments.get("path") or "").strip().replace("\\", "/")
    if not path:
        return
    _FILE_TASK_READ_PATHS.set(_FILE_TASK_READ_PATHS.get() | {path})


def _request_anchors(message: str) -> set[str]:
    anchors: set[str] = set()
    for match in _CODE_ANCHOR_RE.finditer(message):
        raw = next((group for group in match.groups() if group), "")
        for token in re.findall(r"[A-Za-z0-9_$.-]{3,}", raw.lower()):
            cleaned = token.lstrip("#.")
            if cleaned not in _GENERIC_ANCHORS:
                anchors.add(cleaned)
    for match in _BARE_IDENTIFIER_RE.finditer(message):
        cleaned = match.group(1).lower().lstrip("#.")
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


def _document_structure_changes(old: str, new: str) -> list[str]:
    old_counts = _tag_counts(old)
    new_counts = _tag_counts(new)
    return [tag for tag in _DOCUMENT_STRUCTURE_TAGS if old_counts[tag] != new_counts[tag]]


def _file_update_scope_guard(call: ToolCall) -> dict[str, Any] | None:
    if call.tool != "file_update":
        return None

    message = _FILE_TASK_MESSAGE.get()
    if not message or _BROAD_CHANGE_RE.search(message):
        return None

    args = call.arguments
    path = str(args.get("path") or "").strip().replace("\\", "/")
    local_request = bool(_LOCAL_CHANGE_RE.search(message))
    scope_limited = bool(_SCOPE_LIMIT_RE.search(message))

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
        if path and path not in _FILE_TASK_READ_PATHS.get():
            return {
                "ok": False,
                "error": "file_overwrite_without_prior_read",
                "message": (
                    "A full-file overwrite was attempted before the exact target file was successfully read in this request. "
                    "Read it first, then prefer a minimal old/new replacement unless a full rewrite was explicitly requested."
                ),
                "path": path,
                "recovery": {"next_tools": ["file_read", "file_update"]},
            }
        return None

    if "old" not in args or "new" not in args:
        return None

    old = str(args.get("old") or "")
    new = str(args.get("new") or "")
    structure_changes = _document_structure_changes(old, new)
    if structure_changes and (local_request or scope_limited):
        return {
            "ok": False,
            "error": "file_update_unrelated_structure_change",
            "message": (
                "This local edit changes document-level structure tags "
                f"({', '.join(structure_changes)}). That is outside the requested scope unless explicitly requested. "
                "In particular, never replace <style> with <script> (or vice versa) while removing a UI element. "
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
                f"This local request attempted a replacement spanning about {change_lines} lines. "
                "Use a smaller exact replacement around the requested element/reference."
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


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def definitions(self) -> list[ToolDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions)]

    def model_definitions(self) -> list[ToolDefinition]:
        return [definition for definition in self.definitions() if definition.model_visible]

    def definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def has_tool(self, name: str) -> bool:
        return name in self._handlers

    async def run(self, call: ToolCall) -> dict[str, Any]:
        handler = self._handlers.get(call.tool)
        if handler is None:
            raise ValueError(f"Unknown tool: {call.tool}")

        original_arguments = dict(call.arguments)
        _normalize_file_call_arguments(call, get_file_working_root())

        scope_guard = _file_update_scope_guard(call)
        if scope_guard is not None:
            scope_guard["file_working_root"] = get_file_working_root()
            scope_guard["path_base_hint"] = (
                "Relative file paths resolve from file_working_root. The proposed write was blocked before disk mutation; "
                "inspect the exact target and retry with a smaller, request-aligned old/new replacement."
            )
            return scope_guard

        result = await handler(call.arguments)

        if call.tool in _FILE_RELATED_TOOLS and isinstance(result, dict):
            _maybe_update_working_root(
                call=call,
                original_arguments=original_arguments,
                result=result,
            )
            _remember_successful_file_read(call, result)
            result["file_working_root"] = get_file_working_root()
            result["path_base_hint"] = (
                "Relative file paths resolve from file_working_root. file_tree(root=...) changes that logical cwd. "
                "Use ../ to move upward, sibling paths such as ../MK5 to move across projects, or an absolute path "
                "to work outside the initial workspace. The working root is a convenience base, not a sandbox boundary."
            )
        return result

    def merge(self, other: "ToolRegistry") -> None:
        for definition in other.definitions():
            self.register(definition, other._handlers[definition.name])
