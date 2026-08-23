from __future__ import annotations

from MK4.tools.llm_client import _compact_tool_result


def test_missing_required_arguments_does_not_repeat_manual_schema() -> None:
    compact = _compact_tool_result(
        tool="web_research",
        result={
            "ok": False,
            "error": "missing_required_arguments",
            "tool": "web_research",
            "missing_arguments": ["objective"],
            "description": "Long tool description that was already available through tool_manual.",
            "input_schema": {
                "type": "object",
                "properties": {"objective": {"type": "string"}},
                "required": ["objective"],
            },
        },
    )

    assert compact == {
        "ok": False,
        "error": "missing_required_arguments",
        "tool": "web_research",
        "missing_arguments": ["objective"],
    }


def test_failed_tool_history_keeps_error_and_bounded_structured_recovery() -> None:
    compact = _compact_tool_result(
        tool="file_update",
        result={
            "ok": False,
            "error": "file_update_scope_too_broad",
            "message": "x" * 600,
            "path": "MK4/app/static/index.html",
            "recovery": {
                "next_tools": ["file_read", "file_text_search", "file_update"],
                "verbose_hint": "y" * 1000,
            },
        },
    )

    assert compact["ok"] is False
    assert compact["error"] == "file_update_scope_too_broad"
    assert compact["tool"] == "file_update"
    assert compact["path"] == "MK4/app/static/index.html"
    assert len(compact["message"]) <= 240
    assert compact["next_tools"] == ["file_read", "file_text_search", "file_update"]
    assert isinstance(compact["recovery"], dict)
    assert compact["recovery"]["next_tools"] == ["file_read", "file_text_search", "file_update"]
    assert len(compact["recovery"]["verbose_hint"]) <= 700
