from __future__ import annotations

from typing import Any

import pytest

from MK4.core.agent.orchestrator import AgentOrchestrator
from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolCall, ToolDefinition
from MK4.tools.web_search import StubWebSearchTool


class CaptureEmptyMemorySummaryModel:
    def __init__(self) -> None:
        self.memory_summaries: list[list[Any]] = []

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
        self.memory_summaries.append(memory_summary)
        return ModelTurn(final_answer="done")


class ExplicitRecallModel:
    def __init__(self) -> None:
        self.saw_empty_initial_memory = False

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
        if not tool_history:
            self.saw_empty_initial_memory = memory_summary == []
            return ModelTurn(tool_calls=[
                ToolCall(tool="graph_search", arguments={"query": "career", "limit": 8})
            ])
        assert any(event.get("tool") == "graph_search" for event in tool_history)
        return ModelTurn(final_answer="recalled")


@pytest.mark.asyncio
async def test_orchestrator_does_not_push_automatic_memory_summary() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    memory.record_user_utterance(user_id="alice", text="My career memory.", session_id="s1")
    model = CaptureEmptyMemorySummaryModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=GraphToolSuite(memory),
        chat_model=model,
        web_search=StubWebSearchTool(),
    )

    result = await orchestrator.respond(
        user_id="alice",
        message="Do you remember my career?",
        session_id="s1",
    )

    assert result.text == "done"
    assert model.memory_summaries == [[]]
    repo.close()


@pytest.mark.asyncio
async def test_persistent_memory_enters_model_only_after_graph_search_tool_result() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    memory.record_user_utterance(user_id="alice", text="My career memory.", session_id="s1")
    model = ExplicitRecallModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=GraphToolSuite(memory),
        chat_model=model,
        web_search=StubWebSearchTool(),
    )

    result = await orchestrator.respond(
        user_id="alice",
        message="Tell me about my earlier career discussion.",
        session_id="s1",
    )

    assert model.saw_empty_initial_memory is True
    assert result.text == "recalled"
    assert any(event["tool"] == "graph_search" for event in result.tool_events)
    repo.close()
