from __future__ import annotations

from typing import Any

import pytest

from MK4 import config
from MK4.core.agent.orchestrator import AgentOrchestrator
from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.llm_client import ModelTurn
from MK4.tools.terminal_tools import TerminalToolSuite
from MK4.tools.tool_runtime import ToolDefinition
from MK4.tools.web_search import StubWebSearchTool


class BlockedAnswerModel:
    def __init__(self) -> None:
        self.turns = 0

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
        self.turns += 1
        return ModelTurn(final_answer="blocked answer", final_answer_kind="blocked")


class EmptyTurnRecoveryModel:
    def __init__(self) -> None:
        self.turns = 0

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
        self.turns += 1
        if not tool_definitions:
            assert any(
                event.get("tool") == "execution_guard"
                and event.get("result", {}).get("error") == "empty_turn_recovery_exhausted"
                for event in tool_history
            )
            return ModelTurn(final_answer="synthesized after empty turns")
        return ModelTurn()


def build(model: object) -> tuple[AgentOrchestrator, GraphRepository]:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=GraphToolSuite(memory),
        chat_model=model,
        web_search=StubWebSearchTool(),
    )
    return orchestrator, repo


@pytest.mark.asyncio
async def test_blocked_answer_does_not_require_terminal_attempt() -> None:
    model = BlockedAnswerModel()
    orchestrator, repo = build(model)
    orchestrator.register_tool_registry(TerminalToolSuite().build_registry())
    try:
        result = await orchestrator.respond(user_id="alice", message="memory/web task", session_id="s1")
    finally:
        repo.close()

    assert result.text == "blocked answer"
    assert model.turns == 1
    assert "terminal_command" not in result.used_tools


@pytest.mark.asyncio
async def test_repeated_empty_turns_stop_recovery_and_run_final_synthesis(monkeypatch) -> None:
    monkeypatch.setattr(config, "AGENT_MAX_EMPTY_TURN_GUARDS", 2)
    monkeypatch.setattr(config, "AGENT_MAX_ROUNDS", 20)
    model = EmptyTurnRecoveryModel()
    orchestrator, repo = build(model)
    try:
        result = await orchestrator.respond(user_id="alice", message="finish this", session_id="s2")
    finally:
        repo.close()

    assert result.text == "synthesized after empty turns"
    assert model.turns == 3
