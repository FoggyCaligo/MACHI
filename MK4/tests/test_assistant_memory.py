from __future__ import annotations

import asyncio

from MK4.core.graph.assistant_memory import AssistantMemoryRecorder
from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.tool_runtime import ToolCall


def test_assistant_response_is_recalled_after_repository_restart(tmp_path) -> None:
    db_path = tmp_path / "memory.db"

    first_repo = GraphRepository(db_path)
    first_memory = GraphMemoryService(first_repo)
    first_memory.ensure_user_anchor("alice")
    recorder = AssistantMemoryRecorder(first_repo)
    node_id = recorder.record(
        user_id="alice",
        text="SF 소설로 프랭크 허버트의 듄과 어슐러 K. 르 귄의 어둠의 왼손을 추천합니다.",
        session_id="s1",
    )
    assert node_id is not None
    first_repo.close()

    restarted_repo = GraphRepository(db_path)
    restarted_memory = GraphMemoryService(restarted_repo)
    tools = GraphToolSuite(restarted_memory)

    summary = tools.get_user_memory_summary(
        user_id="alice",
        query="듄 프랭크 허버트",
        limit=5,
    )

    assert summary
    assert any(item["subgraph"]["focus"]["provenance"] == "assistant_utterance" for item in summary)
    assistant_item = next(
        item
        for item in summary
        if item["subgraph"]["focus"]["provenance"] == "assistant_utterance"
    )
    assert "assistant가 사용자(alice)에게 이전에 말한 내용" in assistant_item["label"]
    assert "프랭크 허버트" in assistant_item["raw_label"]
    assert "듄" in assistant_item["raw_label"]
    restarted_repo.close()


def test_graph_search_marks_recalled_assistant_response_as_assistant(tmp_path) -> None:
    repo = GraphRepository(tmp_path / "memory.db")
    memory = GraphMemoryService(repo)
    memory.ensure_user_anchor("alice")
    recorder = AssistantMemoryRecorder(repo)
    recorder.record(
        user_id="alice",
        text="테드 창의 당신 인생의 이야기를 추천합니다.",
        session_id="s1",
    )
    registry = GraphToolSuite(memory).build_registry()

    result = asyncio.run(registry.run(ToolCall(
        tool="graph_search",
        arguments={"user_id": "alice", "query": "테드 창 당신 인생의 이야기"},
    )))

    assert result["results"]
    assistant_result = next(
        item
        for item in result["results"]
        if item["focus"].get("provenance") == "assistant_utterance"
    )
    assert assistant_result["focus"]["speaker"] == "assistant"
    assert assistant_result["source"]["speaker"] == "assistant"
    assert assistant_result["source"]["user_id"] == "alice"
    repo.close()


def test_deleting_user_memory_also_deletes_assistant_responses(tmp_path) -> None:
    repo = GraphRepository(tmp_path / "memory.db")
    memory = GraphMemoryService(repo)
    memory.ensure_user_anchor("alice")
    recorder = AssistantMemoryRecorder(repo)
    node_id = recorder.record(
        user_id="alice",
        text="아이작 아시모프의 파운데이션을 추천합니다.",
        session_id="s1",
    )
    assert node_id is not None
    assert repo.get_node(node_id) is not None

    memory.delete_user_memory("alice")

    assert repo.get_node(node_id) is None
    repo.close()
