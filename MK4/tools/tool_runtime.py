from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
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
_WORKSPACE_RELATIVE_BYPASS_PREFIXES = (".mk4_uploads/",)


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
    normalized = _normalize_root_value(root)
    return _FILE_WORKING_ROOT.set(normalized)


def reset_file_working_root(token: Token[str]) -> None:
    _FILE_WORKING_ROOT.reset(token)


def _normalize_root_value(root: str) -> str:
    value = str(root or ".").strip().replace("\\", "/") or "."
    while value.startswith("./"):
        value = value[2:]
    return value.strip("/") or "."


def _is_absolute_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))


def _is_workspace_relative_bypass(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return any(normalized.startswith(prefix) for prefix in _WORKSPACE_RELATIVE_BYPASS_PREFIXES)


def _resolve_under_working_root(value: str, working_root: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raw = "."
    if working_root in {"", "."} or _is_absolute_path(raw) or _is_workspace_relative_bypass(raw):
        return raw
    while raw.startswith("./"):
        raw = raw[2:]
    root = _normalize_root_value(working_root)
    if raw in {"", "."}:
        return root
    if raw == root or raw.startswith(root + "/"):
        return raw
    return f"{root}/{raw}"


def _normalize_file_call_arguments(call: ToolCall, working_root: str) -> None:
    if call.tool not in _FILE_RELATED_TOOLS or working_root in {"", "."}:
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


def _maybe_adopt_working_root(*, call: ToolCall, original_arguments: dict[str, Any], result: dict[str, Any]) -> None:
    if get_file_working_root() not in {"", "."}:
        return
    if call.tool not in _FILE_ROOT_TOOLS or result.get("ok") is not True:
        return
    candidate = _normalize_root_value(str(original_arguments.get("root") or "."))
    if candidate in {"", ".", ".."} or "/" in candidate or _is_absolute_path(candidate):
        return
    _FILE_WORKING_ROOT.set(candidate)


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
        result = await handler(call.arguments)

        if call.tool in _FILE_RELATED_TOOLS and isinstance(result, dict):
            _maybe_adopt_working_root(
                call=call,
                original_arguments=original_arguments,
                result=result,
            )
            result["file_working_root"] = get_file_working_root()
            result["path_base_hint"] = (
                "Relative file paths resolve from file_working_root. "
                "The active root may be any discovered project/subdirectory. Paths relative to that root, "
                "with or without a leading './', are both valid."
            )
        return result

    def merge(self, other: "ToolRegistry") -> None:
        for definition in other.definitions():
            self.register(definition, other._handlers[definition.name])
