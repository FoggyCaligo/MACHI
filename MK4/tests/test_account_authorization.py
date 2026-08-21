from __future__ import annotations

from typing import Any

import pytest

from MK4.tools.account_authorization import (
    AccountAuthorizationChatModel,
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
async def test_owner_role_adds_system_authorization() -> None:
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

    assert "owner account" in inner.system
    assert "system-wide changes" in inner.system
    assert "actual tool or OS denies" in inner.system


@pytest.mark.asyncio
async def test_non_owner_role_does_not_receive_owner_authorization() -> None:
    inner = CaptureModel()
    wrapper = AccountAuthorizationChatModel(inner)
    token = set_account_role("trial")
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
