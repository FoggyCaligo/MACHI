from __future__ import annotations

from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolDefinition


_TOOL_SUMMARY_LIMIT = 180


class ToolCatalogChatModel:
    """Expose a compact tool-name/summary catalog before delegating model work."""

    def __init__(self, delegate: ChatModel) -> None:
        self._delegate = delegate

    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        return await self._delegate.next_turn(
            system=_system_with_tool_catalog(system, tool_definitions),
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )


def _system_with_tool_catalog(system: str, tool_definitions: list[ToolDefinition]) -> str:
    if not tool_definitions:
        return system
    catalog = "\n".join(
        f"- {definition.name}: {_compact_tool_summary(definition.description)}"
        for definition in tool_definitions
    )
    return (
        system
        + "\n\nAvailable tools (name + short purpose only; use tool_manual for full schema/details):\n"
        + catalog
    )


def _compact_tool_summary(description: str) -> str:
    one_line = " ".join(str(description or "").split())
    if len(one_line) <= _TOOL_SUMMARY_LIMIT:
        return one_line
    return one_line[: _TOOL_SUMMARY_LIMIT - 3] + "..."
