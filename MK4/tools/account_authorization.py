from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolDefinition


_ACCOUNT_ROLE: ContextVar[str] = ContextVar("account_role", default="owner")


def set_account_role(role: str) -> Token[str]:
    return _ACCOUNT_ROLE.set(str(role))


def reset_account_role(token: Token[str]) -> None:
    _ACCOUNT_ROLE.reset(token)


def get_authorization_context() -> dict[str, Any]:
    role = _ACCOUNT_ROLE.get()
    if role == "owner":
        return {
            "role": "owner",
            "tool_access": "all_exposed_tools",
            "system_changes": True,
            "external_paths": True,
            "startup_registration": True,
            "registry": True,
            "permission_rule": "attempt_tool_then_trust_real_os_result",
        }
    return {
        "role": role,
        "tool_access": "exposed_tools_only",
        "system_changes": False,
        "external_paths": False,
        "startup_registration": False,
        "registry": False,
        "permission_rule": "respect_exposed_tool_scope",
    }


class AccountAuthorizationChatModel:
    """Keep account role in request context; model-facing authority is structured in the payload."""

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
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )
