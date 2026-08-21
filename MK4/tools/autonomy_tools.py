from __future__ import annotations

from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolDefinition


_AUTONOMY_RETRY_INSTRUCTION = """
The previous turn returned blocked before any exposed tool produced a real execution failure.
The tools exposed to you are part of your capabilities as MK4. Do not assume that you lack access, permission, or the ability to act merely because you are an LLM.
When a plausible exposed tool can perform the user's requested action, use it instead of replacing execution with instructions.
If a tool or the operating system actually rejects the action, return blocked and ground that claim in the real tool result.
If no exposed tool can perform the requested action, you may still return blocked after reconsidering the available capabilities.
""".strip()


class AutonomyChatModel:
    """Give an unsupported blocked turn one structural second chance."""

    def __init__(self, delegate: ChatModel, *, max_retries: int = 1) -> None:
        self._delegate = delegate
        self._max_retries = max(0, max_retries)

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
        turn = await self._delegate.next_turn(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )
        retries = 0
        while retries < self._max_retries and _should_retry_unsupported_blocked(
            turn,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        ):
            retries += 1
            retry_history = [
                *tool_history,
                {
                    "tool": "autonomy_guard",
                    "arguments": {},
                    "result": {
                        "ok": False,
                        "error": "blocked_without_tool_failure",
                        "message": _AUTONOMY_RETRY_INSTRUCTION,
                        "rejected_final_answer": (turn.final_answer or "")[:1000],
                    },
                },
            ]
            turn = await self._delegate.next_turn(
                system=f"{system}\n\n{_AUTONOMY_RETRY_INSTRUCTION}",
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=retry_history,
            )
        return turn


def _should_retry_unsupported_blocked(
    turn: ModelTurn,
    *,
    tool_definitions: list[ToolDefinition],
    tool_history: list[dict[str, Any]],
) -> bool:
    if turn.final_answer_kind != "blocked" or turn.tool_calls:
        return False
    if not tool_definitions:
        return False
    return not _has_real_tool_failure(tool_history)


def _has_real_tool_failure(tool_history: list[dict[str, Any]]) -> bool:
    for event in tool_history:
        if event.get("tool") in {"execution_guard", "autonomy_guard", "file_text_activation"}:
            continue
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("ok") is False:
            return True
        if "returncode" in result and result.get("returncode") not in {None, 0}:
            return True
    return False
