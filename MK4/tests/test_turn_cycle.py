from __future__ import annotations

import asyncio
from typing import Any

import pytest

from MK4.core.graph.model_managed_memory import ModelManagedGraphMemoryService
from MK4.core.graph.repository import GraphRepository
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.llm_client import ModelTurn
from MK4.tools.memory_context import (
    get_memory_turn_scope,
    get_writable_terms,
    register_recalled_node_ids,
    reset_memory_turn_scope,
    reset_memory_user_id,
    set_memory_draft_answer,
    set_memory_turn_scope,
    set_memory_user_id,
)
from MK4.tools.tool_runtime import ToolCall, ToolDefinition
from MK4.tools.turn_cycle import (
    TurnCycleChatModel,
    TurnCycleToolSuite,
    reset_turn_cycle_state,
    set_turn_cycle_state,
)


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, input_schema={"type": "object"})


class PhaseModel:
    def __init__(self) -> None:
        self.exposed: list[list[str]] = []
        self.commit_call_count = 0

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
        names = [definition.name for definition in tool_definitions]
        self.exposed.append(names)
        if names == ["graph_search"]:
            return ModelTurn(tool_calls=[ToolCall(tool="graph_search", arguments={})])
        if set(names).issubset({"write_memory", "revise_memory", "finish_memory_commit", "tool_manual"}):
            self.commit_call_count += 1
            if self.commit_call_count == 1:
                return ModelTurn(tool_calls=[ToolCall(
                    tool="write_memory",
                    arguments={
                        "subject": {"kind": "user"},
                        "relation": "said",
                        "object": {"kind": "concept", "term_id": "user:0:0"},
                    },
                )])
            return ModelTurn(tool_calls=[ToolCall(tool="finish_memory_commit", arguments={})])
        return ModelTurn(final_answer="hello back")


@pytest.mark.asyncio
async def test_turn_cycle_runs_one_model_call_per_agent_loop_round() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)
    registry = GraphToolSuite(memory).build_registry()
    registry.merge(TurnCycleToolSuite().build_registry())
    model_inner = PhaseModel()
    model = TurnCycleChatModel(model_inner)
    definitions = [
        _definition("graph_search"),
        _definition("file_read"),
        _definition("write_memory"),
        _definition("revise_memory"),
        _definition("_begin_memory_commit"),
        _definition("finish_memory_commit"),
    ]
    user_token = set_memory_user_id("alice")
    memory_token = set_memory_turn_scope("hello")
    cycle_token = set_turn_cycle_state()
    history: list[dict[str, Any]] = []
    try:
        first = await model.next_turn(
            system="s", user_message="u", model=None, memory_summary=[],
            tool_definitions=definitions, tool_history=history,
        )
        assert first.tool_calls[0].tool == "graph_search"
        assert len(model_inner.exposed) == 1
        recall_result = await registry.run(ToolCall(
            tool="graph_search",
            arguments={"user_id": "alice", "limit": 4},
        ))
        history.append({"tool": "graph_search", "arguments": {}, "result": recall_result})

        second = await model.next_turn(
            system="s", user_message="u", model=None, memory_summary=[],
            tool_definitions=definitions, tool_history=history,
        )
        assert second.final_answer is None
        assert second.tool_calls[0].tool == "_begin_memory_commit"
        assert len(model_inner.exposed) == 2
        assert "file_read" in model_inner.exposed[1]
        assert "write_memory" not in model_inner.exposed[1]
        assert "_begin_memory_commit" not in model_inner.exposed[1]
        begin_result = await registry.run(second.tool_calls[0])
        assert begin_result["ok"] is True
        history.append({"tool": "_begin_memory_commit", "arguments": {}, "result": begin_result})

        third = await model.next_turn(
            system="s", user_message="u", model=None, memory_summary=[],
            tool_definitions=definitions, tool_history=history,
        )
        assert third.tool_calls[0].tool == "write_memory"
        assert len(model_inner.exposed) == 3
        assert "finish_memory_commit" not in model_inner.exposed[2]
        assert "write_memory" in model_inner.exposed[2]
        assert "revise_memory" in model_inner.exposed[2]
        write_result = await registry.run(third.tool_calls[0])
        assert write_result["ok"] is True
        history.append({"tool": "write_memory", "arguments": third.tool_calls[0].arguments, "result": write_result})

        fourth = await model.next_turn(
            system="s", user_message="u", model=None, memory_summary=[],
            tool_definitions=definitions, tool_history=history,
        )
        assert fourth.tool_calls[0].tool == "finish_memory_commit"
        assert len(model_inner.exposed) == 4
        assert "finish_memory_commit" in model_inner.exposed[3]
        finish_result = await registry.run(fourth.tool_calls[0])
        assert finish_result["ok"] is True
        history.append({"tool": "finish_memory_commit", "arguments": {}, "result": finish_result})

        fifth = await model.next_turn(
            system="s", user_message="u", model=None, memory_summary=[],
            tool_definitions=definitions, tool_history=history,
        )
        assert fifth.final_answer == "hello back"
        assert len(model_inner.exposed) == 4
        assert get_memory_turn_scope().mutation_succeeded is True
    finally:
        reset_turn_cycle_state(cycle_token)
        reset_memory_turn_scope(memory_token)
        reset_memory_user_id(user_token)
        repo.close()


def test_new_nodes_require_current_turn_term_id() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)
    registry = GraphToolSuite(memory).build_registry()
    user_token = set_memory_user_id("alice")
    memory_token = set_memory_turn_scope("alpha beta")
    try:
        set_memory_draft_answer("gamma")
        terms = get_writable_terms()
        beta_term = next(item["term_id"] for item in terms if item["text"] == "beta")
        result = asyncio.run(registry.run(ToolCall(
            tool="write_memory",
            arguments={
                "subject": {"kind": "user"},
                "relation": "mentioned",
                "object": {"kind": "concept", "term_id": beta_term},
            },
        )))
        assert result["ok"] is True
        assert result["object_node_id"] in get_memory_turn_scope().created_node_ids

        with pytest.raises(ValueError, match="term_id is not writable"):
            asyncio.run(registry.run(ToolCall(
                tool="write_memory",
                arguments={
                    "subject": {"kind": "user"},
                    "relation": "mentioned",
                    "object": {"kind": "concept", "term_id": "user:9:9"},
                },
            )))
    finally:
        reset_memory_turn_scope(memory_token)
        reset_memory_user_id(user_token)
        repo.close()


def test_revise_connect_reinforces_in_scope_edge_and_allows_chaining() -> None:
    repo = GraphRepository(":memory:")
    memory = ModelManagedGraphMemoryService(repo)
    first = memory.write_semantic_memory(
        user_id="alice",
        subject={"kind": "user"},
        relation="mentioned",
        object_={"kind": "concept", "label": "A"},
    )
    second = memory.write_semantic_memory(
        user_id="alice",
        subject={"kind": "user"},
        relation="mentioned",
        object_={"kind": "concept", "label": "B"},
    )
    registry = GraphToolSuite(memory).build_registry()
    user_token = set_memory_user_id("alice")
    memory_token = set_memory_turn_scope("A then B then C")
    try:
        set_memory_draft_answer("A before B before C")
        register_recalled_node_ids({first["object_node_id"], second["object_node_id"]})

        one = asyncio.run(registry.run(ToolCall(
            tool="revise_memory",
            arguments={
                "operation": "connect",
                "subject": {"node_id": first["object_node_id"]},
                "relation": "before",
                "object": {"node_id": second["object_node_id"]},
            },
        )))
        two = asyncio.run(registry.run(ToolCall(
            tool="revise_memory",
            arguments={
                "operation": "connect",
                "subject": {"node_id": first["object_node_id"]},
                "relation": "before",
                "object": {"node_id": second["object_node_id"]},
            },
        )))
        assert one["support_count"] == 1
        assert two["support_count"] == 2

        c_term = next(item["term_id"] for item in get_writable_terms() if item["text"] == "C")
        created = asyncio.run(registry.run(ToolCall(
            tool="write_memory",
            arguments={
                "subject": {"node_id": second["object_node_id"]},
                "relation": "before",
                "object": {"kind": "concept", "term_id": c_term},
            },
        )))
        assert created["object_node_id"] in get_memory_turn_scope().created_node_ids

        chained = asyncio.run(registry.run(ToolCall(
            tool="revise_memory",
            arguments={
                "operation": "connect",
                "subject": {"node_id": created["object_node_id"]},
                "relation": "follows",
                "object": {"node_id": first["object_node_id"]},
            },
        )))
        assert chained["ok"] is True
    finally:
        reset_memory_turn_scope(memory_token)
        reset_memory_user_id(user_token)
        repo.close()
