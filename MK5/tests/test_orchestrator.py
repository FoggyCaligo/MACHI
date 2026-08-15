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


class FollowupFileCorrectionModel:
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
        if self._turn == 1 or (
            tool_history
            and all(event.get("tool") == "internet_search" for event in tool_history)
        ):
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "content": "감성, 샤워",
                        "mode": "append",
                    },
                )
            ])
        if any(event.get("tool") == "file_update" for event in tool_history):
            return ModelTurn(final_answer="완료했습니다.")
        assert "Previous file operation" in user_message
        assert "../playlist2/pli_file/tag.txt" in user_message
        return ModelTurn(tool_calls=[
            ToolCall(
                tool="file_update",
                arguments={
                    "path": "../playlist2/pli_file/tag.txt",
                    "old": "감성, 샤워",
                    "new": "감성 샤워",
                },
            )
        ])


class PrematureToolCompletionClaimModel:
    def __init__(self) -> None:
        self.saw_completion_guard = False

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
            return ModelTurn(
                final_answer="추가했습니다.",
                final_answer_kind="tool_completion",
                completion_tools=["file_update"],
            )
        if any(
            event.get("tool") == "execution_guard"
            and event.get("result", {}).get("error") == "completion_tool_not_run"
            for event in tool_history
        ):
            self.saw_completion_guard = True
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "content": "감성 샤워",
                        "mode": "append",
                    },
                )
            ])
        return ModelTurn(
            final_answer="추가했습니다.",
            final_answer_kind="tool_completion",
            completion_tools=["file_update"],
        )


class EmptyAfterFileReadModel:
    def __init__(self) -> None:
        self.saw_empty_read_guard = False

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
            return ModelTurn(
                final_answer="추가했습니다.",
                final_answer_kind="tool_completion",
                completion_tools=["file_update"],
            )
        if any(
            event.get("tool") == "execution_guard"
            and event.get("result", {}).get("error") == "empty_turn_after_file_read"
            for event in tool_history
        ):
            self.saw_empty_read_guard = True
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "content": "감성 샤워",
                        "mode": "append",
                    },
                )
            ])
        if any(event.get("tool") == "file_read" for event in tool_history):
            return ModelTurn()
        return ModelTurn(tool_calls=[
            ToolCall(
                tool="file_read",
                arguments={"path": "../playlist2/pli_file/tag.txt"},
            )
        ])


class EmptyAfterVerifiedFileUpdateModel:
    def __init__(self) -> None:
        self.saw_empty_guard_after_verification = False

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
        file_reads = [event for event in tool_history if event.get("tool") == "file_read"]
        has_update = any(event.get("tool") == "file_update" for event in tool_history)
        if any(
            event.get("tool") == "execution_guard"
            and event.get("result", {}).get("error") == "empty_turn_after_file_read"
            for event in tool_history
        ):
            self.saw_empty_guard_after_verification = True
            return ModelTurn(
                final_answer="추가했습니다.",
                final_answer_kind="tool_completion",
                completion_tools=["file_update", "file_read"],
            )
        if has_update and len(file_reads) >= 2:
            return ModelTurn()
        if has_update:
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_read",
                    arguments={"path": "../playlist2/pli_file/tag.txt"},
                )
            ])
        if file_reads:
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "content": "감성, 샤워",
                        "mode": "append",
                    },
                )
            ])
        return ModelTurn(tool_calls=[
            ToolCall(
                tool="file_read",
                arguments={"path": "../playlist2/pli_file/tag.txt"},
            )
        ])


class InvalidFileUpdateThenRetryModel:
    def __init__(self) -> None:
        self.saw_failed_mutation_guard = False

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
        if any(
            event.get("tool") == "file_update"
            and event.get("result", {}).get("ok") is True
            for event in tool_history
        ):
            return ModelTurn(
                final_answer="콤마를 제거했습니다.",
                final_answer_kind="tool_completion",
                completion_tools=["file_update"],
            )
        if any(
            event.get("tool") == "execution_guard"
            and event.get("result", {}).get("error") == "empty_turn_after_failed_file_mutation"
            for event in tool_history
        ):
            self.saw_failed_mutation_guard = True
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "old": "감성, 샤워",
                        "new": "감성 샤워",
                    },
                )
            ])
        if any(
            event.get("tool") == "file_update"
            and event.get("result", {}).get("ok") is not True
            for event in tool_history
        ):
            return ModelTurn()
        if any(event.get("tool") == "file_read" for event in tool_history):
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "old": "감성, 샤워",
                        "content": "감성 샤워",
                        "mode": "overwrite",
                    },
                )
            ])
        return ModelTurn(tool_calls=[
            ToolCall(
                tool="file_read",
                arguments={"path": "../playlist2/pli_file/tag.txt"},
            )
        ])


class PreviousToolContextModel:
    def __init__(self) -> None:
        self.messages: list[str] = []

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
        if "Current user message:\n../playlist2/pli" in user_message:
            if not any(event.get("tool") == "terminal_command" for event in tool_history):
                return ModelTurn(tool_calls=[
                    ToolCall(
                        tool="terminal_command",
                        arguments={"command": "Get-ChildItem -Path ../playlist2/pli/*.mp3"},
                    )
                ])
            return ModelTurn(final_answer="mp3 검색은 실패했습니다.")
        if "Current user message:\n.mp3가 아니라 .opus" in user_message:
            return ModelTurn(final_answer=".opus 확장자로 이해했습니다.")
        if tool_history:
            return ModelTurn(final_answer="opus 검색을 진행했습니다.")
        assert "Previous tool operation" in user_message
        assert "*.mp3" in user_message
        assert "../playlist2/pli" in user_message
        assert ".opus" in user_message
        return ModelTurn(tool_calls=[
            ToolCall(
                tool="terminal_command",
                arguments={"command": "Get-ChildItem -Path ../playlist2/pli/*.opus"},
            )
        ])


class MalformedThenScriptModel:
    def __init__(self) -> None:
        self.saw_parse_guard = False

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
        if any(event.get("tool") == "terminal_command" for event in tool_history):
            return ModelTurn(final_answer="스크립트를 실행했습니다.")
        if any(event.get("tool") == "file_create" for event in tool_history):
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="terminal_command",
                    arguments={"command": "python artists.py"},
                )
            ])
        if any(
            event.get("tool") == "execution_guard"
            and event.get("result", {}).get("error") == "model_output_parse_failed"
            for event in tool_history
        ):
            self.saw_parse_guard = True
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="file_create",
                    arguments={
                        "path": "artists.py",
                        "content": "print('artist')\n",
                    },
                )
            ])
        raise RuntimeError("Model response must be valid JSON with final_answer and tool_calls: Unterminated string")


class EmptyInitialThenToolModel:
    def __init__(self) -> None:
        self.saw_empty_initial_guard = False

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
        if any(event.get("tool") == "terminal_command" for event in tool_history):
            return ModelTurn(final_answer="실행했습니다.")
        if any(
            event.get("tool") == "execution_guard"
            and event.get("result", {}).get("error") in {"empty_initial_turn", "empty_turn_after_tool"}
            for event in tool_history
        ):
            self.saw_empty_initial_guard = True
            return ModelTurn(tool_calls=[
                ToolCall(
                    tool="terminal_command",
                    arguments={"command": "python -c \"print('ok')\""},
                )
            ])
        return ModelTurn()


class MixedFinalAndToolCallModel:
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
            return ModelTurn(
                final_answer="수정했습니다.",
                final_answer_kind="tool_completion",
                completion_tools=["file_update"],
            )
        return ModelTurn(
            final_answer="수정했습니다.",
            tool_calls=[
                ToolCall(
                    tool="file_update",
                    arguments={
                        "path": "../playlist2/pli_file/tag.txt",
                        "old": "감성, 샤워",
                        "new": "감성 샤워",
                    },
                )
            ],
            final_answer_kind="tool_completion",
            completion_tools=["file_update"],
        )


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


@pytest.mark.asyncio
async def test_orchestrator_passes_previous_file_operation_for_followup_correction(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli_file"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    target_file = target_dir / "tag.txt"
    target_file.write_text("", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = FollowupFileCorrectionModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(workspace).build_registry())

    await orchestrator.respond(
        user_id="alice",
        message="tag.txt에 감성, 샤워를 추가해줘.",
        model=None,
        session_id="s1",
    )
    result = await orchestrator.respond(
        user_id="alice",
        message="콤마는 없애줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "완료했습니다."
    assert "Previous file operation" in chat_model.messages[-1]
    assert target_file.read_text(encoding="utf-8") == "감성 샤워"
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_rejects_tool_completion_claim_without_tool_evidence(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli_file"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    target_file = target_dir / "tag.txt"
    target_file.write_text("고음\n", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = PrematureToolCompletionClaimModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(workspace).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="../playlist2/pli_file/tag.txt 맨 마지막 줄에 감성 샤워를 추가해줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "추가했습니다."
    assert chat_model.saw_completion_guard is True
    assert any(event["tool"] == "file_update" for event in result.tool_events)
    assert target_file.read_text(encoding="utf-8") == "고음\n감성 샤워"
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_continues_after_empty_turn_following_file_read(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli_file"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    target_file = target_dir / "tag.txt"
    target_file.write_text("고음\n", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = EmptyAfterFileReadModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(workspace).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="../playlist2/pli_file/tag.txt 맨 마지막 줄에 감성 샤워를 추가해줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "추가했습니다."
    assert chat_model.saw_empty_read_guard is True
    file_tools = [event["tool"] for event in result.tool_events if event["tool"].startswith("file_")]
    assert file_tools == ["file_read", "file_update"]
    assert target_file.read_text(encoding="utf-8") == "고음\n감성 샤워"
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_allows_llm_final_after_verified_file_update_empty_turn(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli_file"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    target_file = target_dir / "tag.txt"
    target_file.write_text("고음\n", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = EmptyAfterVerifiedFileUpdateModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(workspace).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="../playlist2/pli_file/tag.txt 맨 마지막 줄에 감성, 샤워를 한 줄로 추가해줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "추가했습니다."
    assert chat_model.saw_empty_guard_after_verification is True
    file_tools = [event["tool"] for event in result.tool_events if event["tool"].startswith("file_")]
    assert file_tools == ["file_read", "file_update", "file_read"]
    assert target_file.read_text(encoding="utf-8") == "고음\n감성, 샤워"
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_guides_retry_after_invalid_file_update_arguments(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli_file"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    target_file = target_dir / "tag.txt"
    target_file.write_text("고음\n감성, 샤워", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = InvalidFileUpdateThenRetryModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(workspace).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="../playlist2/pli_file/tag.txt의 마지막 줄에서 콤마를 지워줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "콤마를 제거했습니다."
    assert chat_model.saw_failed_mutation_guard is True
    file_updates = [event for event in result.tool_events if event["tool"] == "file_update"]
    assert file_updates[0]["result"]["ok"] is False
    assert file_updates[1]["result"]["ok"] is True
    assert target_file.read_text(encoding="utf-8") == "고음\n감성 샤워"
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_preserves_previous_tool_context_across_correction_turn(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    (target_dir / "스텔 리제 - a.opus").write_text("", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = PreviousToolContextModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(TerminalToolSuite(workspace).build_registry())

    await orchestrator.respond(
        user_id="alice",
        message="../playlist2/pli",
        model=None,
        session_id="s1",
    )
    await orchestrator.respond(
        user_id="alice",
        message=".mp3가 아니라 .opus 형태로 저장되어 있어서 그래.",
        model=None,
        session_id="s1",
    )
    result = await orchestrator.respond(
        user_id="alice",
        message="응. 진행해줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "opus 검색을 진행했습니다."
    terminal_events = [event for event in result.tool_events if event["tool"] == "terminal_command"]
    assert terminal_events[-1]["arguments"]["command"] == "Get-ChildItem -Path ../playlist2/pli/*.opus"
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_recovers_from_malformed_model_json_for_script_task(tmp_path) -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = MalformedThenScriptModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(tmp_path).build_registry())
    orchestrator.register_tool_registry(TerminalToolSuite(tmp_path).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="파이썬 스크립트 파일을 새로 만들어서 실행해줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "스크립트를 실행했습니다."
    assert chat_model.saw_parse_guard is True
    assert (tmp_path / "artists.py").read_text(encoding="utf-8") == "print('artist')\n"
    assert [event["tool"] for event in result.tool_events if event["tool"] != "internet_search"] == [
        "file_create",
        "terminal_command",
    ]
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_recovers_from_empty_initial_model_turn(tmp_path) -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    chat_model = EmptyInitialThenToolModel()
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=chat_model,
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(TerminalToolSuite(tmp_path).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="스크립트를 실행해줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "실행했습니다."
    assert chat_model.saw_empty_initial_guard is True
    assert any(event["tool"] == "terminal_command" for event in result.tool_events)
    repo.close()


@pytest.mark.asyncio
async def test_orchestrator_runs_tool_calls_before_mixed_final_answer(tmp_path) -> None:
    workspace = tmp_path / "MACHI"
    target_dir = tmp_path / "playlist2" / "pli_file"
    workspace.mkdir()
    target_dir.mkdir(parents=True)
    target_file = target_dir / "tag.txt"
    target_file.write_text("감성, 샤워", encoding="utf-8")

    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    graph_tools = GraphToolSuite(memory)
    orchestrator = AgentOrchestrator(
        memory_service=memory,
        graph_tools=graph_tools,
        chat_model=MixedFinalAndToolCallModel(),
        web_search=CapturingWebSearchTool(),
    )
    orchestrator.register_tool_registry(WorkspaceFileToolSuite(workspace).build_registry())

    result = await orchestrator.respond(
        user_id="alice",
        message="../playlist2/pli_file/tag.txt에서 콤마를 지워줘.",
        model=None,
        session_id="s1",
    )

    assert result.text == "수정했습니다."
    assert any(event["tool"] == "file_update" for event in result.tool_events)
    assert target_file.read_text(encoding="utf-8") == "감성 샤워"
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

