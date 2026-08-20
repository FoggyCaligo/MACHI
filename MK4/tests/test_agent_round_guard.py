from __future__ import annotations
from typing import Any
import pytest
from MK4 import config
from MK4.core.agent.orchestrator import AgentOrchestrator
from MK4.core.graph.repository import GraphRepository
from MK4.core.graph.service import GraphMemoryService
from MK4.tools.graph_tools import GraphToolSuite
from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_runtime import ToolCall, ToolDefinition
from MK4.tools.web_search import StubWebSearchTool

class RepeatedCallRecoveryModel:
    def __init__(self): self.turns=0
    async def next_turn(self, *, system:str, user_message:str, model:str|None, memory_summary:list[Any], tool_definitions:list[ToolDefinition], tool_history:list[dict[str,Any]]) -> ModelTurn:
        self.turns+=1
        if any(e.get("tool")=="execution_guard" and e.get("result",{}).get("error")=="repeated_identical_tool_call" for e in tool_history): return ModelTurn(final_answer="recovered")
        return ModelTurn(tool_calls=[ToolCall(tool="graph_search",arguments={"query":"same query"})])

class RoundLimitModel:
    def __init__(self): self.turns=0
    async def next_turn(self, *, system:str, user_message:str, model:str|None, memory_summary:list[Any], tool_definitions:list[ToolDefinition], tool_history:list[dict[str,Any]]) -> ModelTurn:
        self.turns+=1
        if not tool_definitions:
            assert any(e.get("tool")=="execution_guard" and e.get("result",{}).get("error")=="max_agent_rounds_reached" for e in tool_history)
            return ModelTurn(final_answer="round limit synthesis")
        return ModelTurn(tool_calls=[ToolCall(tool="graph_search",arguments={"query":f"query-{self.turns}"})])

def build(model):
    repo=GraphRepository(":memory:"); memory=GraphMemoryService(repo)
    return AgentOrchestrator(memory_service=memory,graph_tools=GraphToolSuite(memory),chat_model=model,web_search=StubWebSearchTool()),repo

@pytest.mark.asyncio
async def test_repeated_identical_call_is_blocked_without_ending_agent_loop(monkeypatch):
    monkeypatch.setattr(config,"AGENT_MAX_IDENTICAL_TOOL_CALLS",3); monkeypatch.setattr(config,"AGENT_MAX_ROUNDS",20)
    model=RepeatedCallRecoveryModel(); o,repo=build(model)
    try: result=await o.respond(user_id="alice",message="keep working",session_id="s1")
    finally: repo.close()
    assert result.text=="recovered"; assert model.turns==5
    assert sum(e.get("tool")=="graph_search" for e in result.tool_events)==3

@pytest.mark.asyncio
async def test_global_round_limit_stops_tools_then_runs_final_synthesis(monkeypatch):
    monkeypatch.setattr(config,"AGENT_MAX_ROUNDS",2); monkeypatch.setattr(config,"AGENT_MAX_IDENTICAL_TOOL_CALLS",3)
    model=RoundLimitModel(); o,repo=build(model)
    try: result=await o.respond(user_id="alice",message="long task",session_id="s2")
    finally: repo.close()
    assert result.text=="round limit synthesis"; assert model.turns==3
    assert sum(e.get("tool")=="graph_search" for e in result.tool_events)==2
