from __future__ import annotations

import asyncio

from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.tool_runtime import ToolCall


def test_memory_summary_ends_with_structural_graph_search_note() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    memory.record_user_utterance(
        user_id="alice",
        text="I enjoy TypeScript and frontend work.",
        session_id="s1",
    )
    tools = GraphToolSuite(memory)

    summary = tools.get_user_memory_summary(
        user_id="alice",
        query="frontend",
        limit=5,
    )

    note = summary[-1]
    assert note["node_type"] == "system_note"
    assert note["subgraph"]["focus"]["provenance"] == "system_policy"
    assert "recall_memory" in note["label"]
    assert "partial automatic recall" in note["label"]
    repo.close()


def test_graph_search_accepts_empty_arguments_for_broad_memory_browse() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    memory.record_user_utterance(
        user_id="alice",
        text="I work on a personal AI project.",
        session_id="s1",
    )
    memory.record_user_utterance(
        user_id="alice",
        text="I prefer Vue for frontend work.",
        session_id="s1",
    )
    registry = GraphToolSuite(memory).build_registry()

    result = asyncio.run(registry.run(ToolCall(
        tool="graph_search",
        arguments={"user_id": "alice"},
    )))

    assert result["mode"] == "browse"
    assert result["results"]
    labels = [item["focus"]["label"] for item in result["results"]]
    assert any("personal AI project" in label for label in labels)
    assert any("Vue" in label for label in labels)
    repo.close()


def test_graph_search_schema_allows_browse_without_query_or_node_id() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    registry = GraphToolSuite(memory).build_registry()
    definition = registry.definition("graph_search")

    assert definition is not None
    assert "anyOf" not in definition.input_schema
    assert definition.input_schema.get("required") is None
    repo.close()
