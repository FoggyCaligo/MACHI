from __future__ import annotations

from typing import Any

import pytest

from MK5.core.agent.orchestrator import AgentOrchestrator
from MK5.core.graph.repository import GraphRepository
from MK5.core.graph.service import GraphMemoryService
from MK5.tools.graph_tools import GraphToolSuite
from MK5.tools.llm_client import ModelTurn
from MK5.tools.tool_runtime import ToolCall, ToolDefinition
from MK5.tools.web_search import StubWebSearchTool
from MK5.tools.tool_runtime import ToolRegistry


class FakeToolCallingModel:
    def __init__(self) -> None:
        self._turn = 0

    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[str],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        self._turn += 1
        if self._turn == 1:
            return ModelTurn(tool_calls=[ToolCall(tool="graph_search", arguments={"query": "hello"})])
        assert tool_history
        return ModelTurn(final_answer="done")


class FakeInternetSearchModel:
    def __init__(self) -> None:
        self._turn = 0

    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[str],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        self._turn += 1
        if self._turn == 1:
            return ModelTurn(tool_calls=[ToolCall(tool="internet_search", arguments={"query": "graph memory"})])
        assert tool_history
        return ModelTurn(final_answer="search done")


class FinalOnlyModel:
    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[str],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        return ModelTurn(final_answer="done")


class CapturingWebSearchTool:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="internet_search",
                description="capture search arguments",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "search_nodes": {"type": "array"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    async def _run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        nodes = [str(node) for node in arguments.get("search_nodes", [])]
        return {
            "query": arguments.get("query"),
            "search_nodes": nodes,
            "results": [
                {
                    "title": f"{node} result",
                    "url": f"https://example.com/{node}",
                    "snippet": "result",
                    "source": "stub",
                    "query_node": node,
                }
                for node in nodes
            ],
            "source_errors": [],
        }


@pytest.mark.asyncio
async def test_orchestrator_runs_tool_then_returns_answer() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    memory.record_user_utterance(user_id="alice", text="hello world", session_id="s1")
    graph_tools = GraphToolSuite(memory)
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=FakeToolCallingModel(),
        web_search=StubWebSearchTool(),
    )

    result = await orchestrator.respond(user_id="alice", message="hello", model=None, session_id="s1")

    assert result.text == "done"
    assert "graph_search" in result.used_tools
    assert result.tool_events
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_persists_search_results_after_tool_call() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=FakeInternetSearchModel(),
        web_search=StubWebSearchTool(),
    )

    result = await orchestrator.respond(user_id="alice", message="search graph memory", model=None, session_id="s1")

    assert result.text == "search done"
    assert "internet_search" in result.used_tools
    persisted = memory.graph_search(user_id="alice", query="stub-result", limit=8)
    assert any(item["node_type"] == "search_result" for item in persisted)
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_passes_recorded_concept_nodes_to_internet_search() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=FakeInternetSearchModel(),
        web_search=CapturingWebSearchTool(),
    )

    result = await orchestrator.respond(
        user_id="alice",
        message="Glock features and market significance",
        model=None,
        session_id="s1",
    )

    search_event = next(event for event in result.tool_events if event["tool"] == "internet_search")
    assert "glock" in search_event["arguments"]["search_nodes"]
    assert search_event["result"]["search_nodes"] == search_event["arguments"]["search_nodes"]
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_runs_no_slot_search_when_focus_lacks_search_support() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=FinalOnlyModel(),
        web_search=CapturingWebSearchTool(),
    )

    result = await orchestrator.respond(
        user_id="alice",
        message="Glock features and market significance",
        model=None,
        session_id="s1",
    )

    assert result.text == "done"
    search_event = next(event for event in result.tool_events if event["tool"] == "internet_search")
    assert "glock" in search_event["arguments"]["search_nodes"]
    repo.close()

