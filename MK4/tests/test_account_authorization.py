from __future__ import annotations

from typing import Any

import pytest

from MK4.tools.account_authorization import (
    AccountAuthorizationChatModel,
    get_authorization_context,
    reset_account_role,
    set_account_role,
)
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolDefinition


class CaptureModel:
    def __init__(self) -> None:
        self.system = ""

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
        self.system = system
        return ModelTurn(final_answer="ok")


@pytest.mark.asyncio
async def test_authorization_wrapper_does_not_duplicate_system_prompt() -> None:
    inner = CaptureModel()
    wrapper = AccountAuthorizationChatModel(inner)
    token = set_account_role("owner")
    try:
        await wrapper.next_turn(
            system="base",
            user_message="task",
            model=None,
            memory_summary=[],
            tool_definitions=[],
            tool_history=[],
        )
    finally:
        reset_account_role(token)

    assert inner.system == "base"


def test_owner_authorization_is_structured() -> None:
    token = set_account_role("owner")
    try:
        context = get_authorization_context()
    finally:
        reset_account_role(token)

    assert context["role"] == "owner"
    assert context["tool_access"] == "all_exposed_tools"
    assert context["system_changes"] is True
    assert context["permission_rule"] == "attempt_tool_then_trust_real_os_result"


def test_non_owner_authorization_is_structured() -> None:
    token = set_account_role("trial")
    try:
        context = get_authorization_context()
    finally:
        reset_account_role(token)

    assert context["role"] == "trial"
    assert context["tool_access"] == "exposed_tools_only"
    assert context["system_changes"] is False
