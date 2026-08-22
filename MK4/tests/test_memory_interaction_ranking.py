from __future__ import annotations

import asyncio

from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.tool_runtime import ToolCall


def test_recall_marks_current_utterance_and_derived_facts_as_interaction_memory() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    tools = GraphToolSuite(memory)
    utterance_id = memory.record_user_utterance(
        user_id="alice",
        text="Tell me what you remember about my career.",
        session_id="s1",
    )

    result = asyncio.run(tools.build_registry().run(ToolCall(
        tool="graph_search",
        arguments={
            "user_id": "alice",
            "query": "career",
            "exclude_node_ids": [utterance_id],
        },
    )))

    assert result["ok"] is True
    utterance = repo.get_node(utterance_id)
    assert utterance is not None
    assert utterance.payload["interaction_role"] == "memory_retrieval"

    derived_facts = []
    for edge in repo.edges_for_node(utterance_id):
        if edge.source_id == utterance_id and edge.relation == "derived_fact":
            node = repo.get_node(edge.target_id)
            if node is not None:
                derived_facts.append(node)
    assert derived_facts
    assert all(node.payload["interaction_role"] == "memory_retrieval" for node in derived_facts)
    repo.close()


def test_content_memory_ranks_before_recall_interaction_memory() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    tools = GraphToolSuite(memory)

    memory.record_user_utterance(
        user_id="alice",
        text="I work as a frontend developer and use Vue.",
        session_id="s1",
    )
    memory.record_user_utterance(
        user_id="alice",
        text="I am planning a delivery-driving career after getting a license.",
        session_id="s1",
    )
    recall_utterance_id = memory.record_user_utterance(
        user_id="alice",
        text="Tell me everything you remember about me again.",
        session_id="s1",
    )
    asyncio.run(tools.build_registry().run(ToolCall(
        tool="graph_search",
        arguments={
            "user_id": "alice",
            "exclude_node_ids": [recall_utterance_id],
        },
    )))

    summary = tools.get_user_memory_summary(
        user_id="alice",
        query="",
        limit=2,
    )
    labels = [item["raw_label"] for item in summary if item["node_type"] != "system_note"]

    assert len(labels) == 2
    assert all("remember about me again" not in label for label in labels)
    repo.close()


def test_broad_recall_preserves_interaction_memory_but_places_content_first() -> None:
    repo = GraphRepository(":memory:")
    memory = GraphMemoryService(repo)
    tools = GraphToolSuite(memory)

    memory.record_user_utterance(
        user_id="alice",
        text="I like science fiction novels.",
        session_id="s1",
    )
    recall_utterance_id = memory.record_user_utterance(
        user_id="alice",
        text="What do you remember about me?",
        session_id="s1",
    )
    registry = tools.build_registry()
    asyncio.run(registry.run(ToolCall(
        tool="graph_search",
        arguments={
            "user_id": "alice",
            "exclude_node_ids": [recall_utterance_id],
        },
    )))

    result = asyncio.run(registry.run(ToolCall(
        tool="graph_search",
        arguments={"user_id": "alice", "limit": 12},
    )))
    labels = [item["focus"]["label"] for item in result["results"]]

    content_index = next(index for index, label in enumerate(labels) if "science fiction" in label)
    interaction_index = next(index for index, label in enumerate(labels) if "What do you remember" in label)
    assert content_index < interaction_index
    repo.close()
