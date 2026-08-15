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
from MK5.tools.workspace_tools import WorkspaceFileToolSuite


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


class ContextAwareFileReadModel:
    def __init__(self) -> None:
        self.last_user_message = ""
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
        self.last_user_message = user_message
        self._turn += 1
        if self._turn == 1:
            return ModelTurn(final_answer="ready")
        if not tool_history:
            return ModelTurn(tool_calls=[
                ToolCall(tool="workspace_file", arguments={"action": "read", "path": "README.md"}),
                ToolCall(tool="workspace_file", arguments={"action": "read", "path": "MK5/README.md"}),
            ])
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


@pytest.mark.asyncio
async def test_orchestrator_does_not_no_slot_search_when_memory_summary_exists() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    memory.record_user_utterance(user_id="alice", text="나는 Alice야.", session_id="s1")
    graph_tools = GraphToolSuite(memory)
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=FinalOnlyModel(),
        web_search=CapturingWebSearchTool(),
    )

    result = await orchestrator.respond(
        user_id="alice",
        message="나에 대해 기억하니?",
        model=None,
        session_id="s1",
    )

    assert result.text == "done"
    assert not any(event["tool"] == "internet_search" for event in result.tool_events)
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_passes_recent_context_so_model_can_read_files(tmp_path) -> None:
    (tmp_path / "README.md").write_text("Root project", encoding="utf-8")
    (tmp_path / "MK5").mkdir()
    (tmp_path / "MK5" / "README.md").write_text("MK5 project", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = ContextAwareFileReadModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(tmp_path).build_registry())

    await orchestrator.respond(
        user_id="alice",
        message="루트의 README.md 파일과, MK5 폴더 안의 README.md 파일을 우선 봐줘.",
        model=None,
        session_id="s1",
    )
    result = await orchestrator.respond(
        user_id="alice",
        message="응. 읽어봐줘.",
        model=None,
        session_id="s1",
    )

    file_events = [event for event in result.tool_events if event["tool"] == "workspace_file"]
    assert [event["arguments"]["path"] for event in file_events] == ["README.md", "MK5/README.md"]
    assert file_events[0]["result"]["content"] == "Root project"
    assert file_events[1]["result"]["content"] == "MK5 project"
    assert "루트의 README.md" in chat_model.last_user_message
    assert "응. 읽어봐줘." in chat_model.last_user_message
    repo.close()

