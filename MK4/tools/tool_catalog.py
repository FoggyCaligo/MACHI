from __future__ import annotations

from .tool_runtime import ToolDefinition


_TOOL_SUMMARY_LIMIT = 120


def compact_tool_catalog(tool_definitions: list[ToolDefinition]) -> list[dict[str, str]]:
    """Return name + short purpose only; detailed schemas stay lazy via tool_manual."""
    return [
        {
            "name": definition.name,
            "summary": _compact_tool_summary(definition.description),
        }
        for definition in tool_definitions
    ]


def _compact_tool_summary(description: str) -> str:
    one_line = " ".join(str(description or "").split())
    if len(one_line) <= _TOOL_SUMMARY_LIMIT:
        return one_line
    return one_line[: _TOOL_SUMMARY_LIMIT - 3] + "..."
