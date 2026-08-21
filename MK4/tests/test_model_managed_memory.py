from __future__ import annotations

import asyncio

from MK4.core.graph.model_managed_memory import ModelManagedGraphMemoryService
from MK4.core.graph.repository import GraphRepository
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.memory_context import reset_memory_user_id, set_memory_user_id
from MK4.tools.tool_runtime import ToolCall


def test_raw_user_utterance_does_not_auto_create_fact_nodes() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)

    memory.record_user_utterance(
        user_id="alice",
        text="I prefer chess and frontend work.",
        session_id="s1",
    )

    assert any(node.node_type == "utterance" for node in repo.all_nodes())
    assert not any(node.node_type == "fact" for node in repo.all_nodes())
    repo.close()


def test_duplicate_semantic_memory_reuses_nodes_and_reinforces_support() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)
    subject = {"kind": "user"}
    object_ = {"kind": "concept", "label": "Chess"}

    first = memory.write_semantic_memory(
        user_id="alice",
        subject=subject,
        relation="prefers",
        object_=object_,
    )
    second = memory.write_semantic_memory(
        user_id="alice",
        subject=subject,
        relation="prefers",
        object_={"kind": "concept", "label": "  chess  "},
    )

    assert second["memory_node_id"] == first["memory_node_id"]
    assert second["object_node_id"] == first["object_node_id"]
    assert second["support_count"] == 2
    semantic_nodes = [node for node in repo.all_nodes() if node.node_type == "semantic_memory"]
    entity_nodes = [node for node in repo.all_nodes() if node.node_type == "semantic_entity"]
    assert len(semantic_nodes) == 1
    assert len(entity_nodes) == 1
    repo.close()


def test_revision_keeps_old_memory_as_inactive_history() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)
    original = memory.write_semantic_memory(
        user_id="alice",
        subject={"kind": "user"},
        relation="current_job",
        object_={"kind": "job", "label": "Web developer"},
    )

    revised = memory.revise_semantic_memory(
        user_id="alice",
        memory_node_id=str(original["memory_node_id"]),
        subject={"kind": "user"},
        relation="current_job",
        object_={"kind": "job", "label": "Long-term rental sales"},
    )

    old_node = repo.get_node(str(original["memory_node_id"]))
    new_node = repo.get_node(str(revised["memory_node_id"]))
    assert old_node is not None and old_node.is_active is False
    assert new_node is not None and new_node.is_active is True
    assert old_node.payload["superseded_by"] == new_node.node_id
    assert any(
        edge.source_id == old_node.node_id
        and edge.target_id == new_node.node_id
        and edge.relation == "superseded_by"
        for edge in repo.all_edges()
    )
    repo.close()


def test_graph_tools_write_memory_uses_request_user_context() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)
    registry = GraphToolSuite(memory).build_registry()
    token = set_memory_user_id("alice")
    try:
        result = asyncio.run(registry.run(ToolCall(
            tool="write_memory",
            arguments={
                "subject": {"kind": "user"},
                "relation": "likes",
                "object": {"kind": "concept", "label": "Chess"},
            },
        )))
    finally:
        reset_memory_user_id(token)

    assert result["ok"] is True
    memory_node = repo.get_node(result["memory_node_id"])
    assert memory_node is not None
    assert memory_node.payload["user_id"] == "alice"
    repo.close()


def test_semantic_memory_is_prioritized_in_user_memory_summary() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)
    memory.record_user_utterance(user_id="alice", text="Tell me about memory.", session_id="s1")
    written = memory.write_semantic_memory(
        user_id="alice",
        subject={"kind": "user"},
        relation="career_goal",
        object_={"kind": "goal", "label": "Open a convenience store"},
    )

    summary = memory.user_memory_summary(user_id="alice", query="", limit=2)

    assert summary
    assert summary[0]["node_id"] == written["memory_node_id"]
    assert summary[0]["node_type"] == "semantic_memory"
    repo.close()
