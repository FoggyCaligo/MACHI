from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from .tool_runtime import ToolDefinition, ToolRegistry


_SCRATCHPAD: ContextVar[dict[str, str] | None] = ContextVar("request_scratchpad", default=None)


def start_request_scratchpad() -> Token[dict[str, str] | None]:
    """Start an empty scratchpad for one agent request."""
    return _SCRATCHPAD.set({})


def reset_request_scratchpad(token: Token[dict[str, str] | None]) -> None:
    """Discard the current request scratchpad and restore the previous context."""
    _SCRATCHPAD.reset(token)


def _active_scratchpad() -> dict[str, str] | None:
    return _SCRATCHPAD.get()


class ScratchpadToolSuite:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="scratchpad_create",
                description=(
                    "Create one temporary note for the current user request. "
                    "Use it for intermediate facts, decisions, targets, hypotheses, or next actions worth reusing "
                    "during this agent loop. The scratchpad is cleared after the request."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["note_id", "content"],
                    "additionalProperties": False,
                },
            ),
            self._create,
        )
        registry.register(
            ToolDefinition(
                name="scratchpad_read",
                description=(
                    "Read temporary notes from the current request scratchpad. "
                    "Provide note_id for one note, or omit it to read all current notes."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ),
            self._read,
        )
        registry.register(
            ToolDefinition(
                name="scratchpad_update",
                description=(
                    "Replace the content of an existing temporary note in the current request scratchpad. "
                    "Fails if the note does not exist."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["note_id", "content"],
                    "additionalProperties": False,
                },
            ),
            self._update,
        )
        registry.register(
            ToolDefinition(
                name="scratchpad_delete",
                description=(
                    "Delete an existing temporary note from the current request scratchpad. "
                    "Fails if the note does not exist."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string"},
                    },
                    "required": ["note_id"],
                    "additionalProperties": False,
                },
            ),
            self._delete,
        )
        return registry

    async def _create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        notes = _active_scratchpad()
        if notes is None:
            return {"ok": False, "error": "scratchpad_not_active"}
        note_id = str(arguments.get("note_id") or "").strip()
        content = str(arguments.get("content") or "")
        if not note_id:
            return {"ok": False, "error": "missing_note_id"}
        if not content.strip():
            return {"ok": False, "error": "missing_content", "note_id": note_id}
        if note_id in notes:
            return {"ok": False, "error": "scratchpad_note_exists", "note_id": note_id}
        notes[note_id] = content
        return {"ok": True, "note_id": note_id, "content": content}

    async def _read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        notes = _active_scratchpad()
        if notes is None:
            return {"ok": False, "error": "scratchpad_not_active"}
        note_id = str(arguments.get("note_id") or "").strip()
        if not note_id:
            return {"ok": True, "notes": dict(notes)}
        if note_id not in notes:
            return {"ok": False, "error": "scratchpad_note_not_found", "note_id": note_id}
        return {"ok": True, "note_id": note_id, "content": notes[note_id]}

    async def _update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        notes = _active_scratchpad()
        if notes is None:
            return {"ok": False, "error": "scratchpad_not_active"}
        note_id = str(arguments.get("note_id") or "").strip()
        content = str(arguments.get("content") or "")
        if not note_id:
            return {"ok": False, "error": "missing_note_id"}
        if not content.strip():
            return {"ok": False, "error": "missing_content", "note_id": note_id}
        if note_id not in notes:
            return {"ok": False, "error": "scratchpad_note_not_found", "note_id": note_id}
        notes[note_id] = content
        return {"ok": True, "note_id": note_id, "content": content}

    async def _delete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        notes = _active_scratchpad()
        if notes is None:
            return {"ok": False, "error": "scratchpad_not_active"}
        note_id = str(arguments.get("note_id") or "").strip()
        if not note_id:
            return {"ok": False, "error": "missing_note_id"}
        if note_id not in notes:
            return {"ok": False, "error": "scratchpad_note_not_found", "note_id": note_id}
        del notes[note_id]
        return {"ok": True, "note_id": note_id}
