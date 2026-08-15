from __future__ import annotations

from typing import Any

import pytest

from MK5.core.agent.orchestrator import AgentOrchestrator
from MK5.core.graph.repository import GraphRepository
from MK5.core.graph.service import GraphMemoryService
from MK5.tools.graph_tools import GraphToolSuite
from MK5.tools.llm_client import ModelTurn
from MK5.tools.terminal_tools import TerminalToolSuite
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
                ToolCall(tool="file_read", arguments={"path": "README.md"}),
                ToolCall(tool="file_read", arguments={"path": "MK5/README.md"}),
            ])
        return ModelTurn(final_answer="done")


class PreviousDialogueModel:
    def __init__(self) -> None:
        self.messages: list[str] = []
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
        self.messages.append(user_message)
        self._turn += 1
        if self._turn == 1:
            return ModelTurn(final_answer="graph_search 도구로 확인해보겠습니다.")
        return ModelTurn(final_answer="done")


class TerminalOnlyFileMutationModel:
    def __init__(self) -> None:
        self.saw_mutation_guard = False

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
        if any(event.get("tool") == "file_update" for event in tool_history):
            return ModelTurn(final_answer="수정했습니다.")
        if any(
            event.get("tool") == "execution_guard"
            and event.get("result", {}).get("error") == "terminal_filesystem_change_not_verified"
            for event in tool_history
        ):
            self.saw_mutation_guard = True
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "old": "감성\n샤워",
                        "new": "감성 샤워",
                    },
                )
            ])
        if any(event.get("tool") == "terminal_command" for event in tool_history):
            return ModelTurn(final_answer="수정했습니다.")
        return ModelTurn(tool_calls=[
            ToolCall(
                tool="terminal_command",
                arguments={
                    "command": "echo pretend-edit > terminal-marker.txt",
                },
            )
        ])


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
async def test_orchestrator_passes_previous_dialogue_so_model_can_read_files(tmp_path) -> None:
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

    file_events = [event for event in result.tool_events if event["tool"] == "file_read"]
    assert [event["arguments"]["path"] for event in file_events] == ["README.md", "MK5/README.md"]
    assert file_events[0]["result"]["content"] == "Root project"
    assert file_events[1]["result"]["content"] == "MK5 project"
    assert "루트의 README.md" in chat_model.last_user_message
    assert "응. 읽어봐줘." in chat_model.last_user_message
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_passes_previous_dialogue_turn_for_confirmation() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = PreviousDialogueModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )

    await orchestrator.respond(
        user_id="alice",
        message="나에 대해 기억하니?",
        model=None,
        session_id="s1",
    )
    await orchestrator.respond(
        user_id="alice",
        message="응. 그 도구로 한번 진행해봐.",
        model=None,
        session_id="s1",
    )

    assert "Previous dialogue turn" in chat_model.messages[-1]
    assert "Assistant: graph_search 도구로 확인해보겠습니다." in chat_model.messages[-1]
    assert "응. 그 도구로 한번 진행해봐." in chat_model.messages[-1]
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_rejects_terminal_only_file_mutation_completion(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli_file"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    target_file = target_dir / "tag.txt"
    target_file.write_text("고음\n감성\n샤워", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = TerminalOnlyFileMutationModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(workspace).build_registry())
    orchestrator.register_tool_registry(TerminalToolSuite(workspace).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="현재 루트에서 한 단계 위의 playlist2/pli_file/tag.txt에서 감성과 샤워 사이의 개행을 없애서 한 줄로 만들어줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "수정했습니다."
    assert chat_model.saw_mutation_guard is True
    assert any(event["tool"] == "terminal_command" for event in result.tool_events)
    assert any(event["tool"] == "file_update" for event in result.tool_events)
    assert target_file.read_text(encoding="utf-8") == "고음\n감성 샤워"
    repo.close()


def test_memory_local_activation_carries_previous_non_overlapping_nodes() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    first_utterance_id = memory.record_user_utterance(
        user_id="alice",
        text="playlist2 폴더의 tag.txt를 확인했다.",
        session_id="s1",
    )
    first_activation = memory.local_activation_node_ids_for_utterance(
        user_id="alice",
        utterance_id=first_utterance_id,
    )

    second_utterance_id = memory.record_user_utterance(
        user_id="alice",
        text="다음 작업으로 넘어가자.",
        session_id="s1",
    )
    second_activation = memory.local_activation_node_ids_for_utterance(
        user_id="alice",
        utterance_id=second_utterance_id,
        previous_activation_node_ids=first_activation,
    )

    assert second_utterance_id in second_activation
    assert first_activation - {second_utterance_id}
    assert (first_activation - {second_utterance_id}).issubset(second_activation)
    repo.close()


def test_memory_activation_weights_decay_previous_non_overlapping_nodes() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    first_utterance_id = memory.record_user_utterance(
        user_id="alice",
        text="playlist2 폴더의 tag.txt를 확인했다.",
        session_id="s1",
    )
    first_activation = memory.local_activation_node_ids_for_utterance(
        user_id="alice",
        utterance_id=first_utterance_id,
    )
    second_utterance_id = memory.record_user_utterance(
        user_id="alice",
        text="sllm 프로젝트를 다시 확인하자.",
        session_id="s1",
    )

    weights = memory.local_activation_node_weights_for_utterance(
        user_id="alice",
        utterance_id=second_utterance_id,
        previous_activation_node_ids=first_activation,
        previous_weight=0.5,
    )
    second_current = memory.local_activation_node_ids_for_utterance(
        user_id="alice",
        utterance_id=second_utterance_id,
    )
    previous_only = first_activation - second_current

    assert previous_only
    assert all(weights[node_id] == 1.0 for node_id in second_current)
    assert all(weights[node_id] == 0.5 for node_id in previous_only)
    repo.close()

