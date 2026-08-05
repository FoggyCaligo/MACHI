from __future__ import annotations

from dataclasses import dataclass, field

from ... import config
from ...tools.graph_tools import GraphToolSuite
from ...tools.llm_client import ChatModel
from ...tools.tool_runtime import ToolCall, ToolRegistry
from ...tools.web_search import WebSearchTool
from ..graph.service import GraphMemoryService
from .prompts import SYSTEM_PROMPT


@dataclass
class AgentResponse:
    text: str
    used_tools: list[str] = field(default_factory=list)
    memory_writes: list[str] = field(default_factory=list)
    tool_events: list[dict] = field(default_factory=list)


class AgentOrchestrator:
    def __init__(
        self,
        *,
        memory_service: GraphMemoryService,
        graph_tools: GraphToolSuite,
        chat_model: ChatModel,
        web_search: WebSearchTool,
    ) -> None:
        self._memory_service = memory_service
        self._graph_tools = graph_tools
        self._chat_model = chat_model
        self._web_search = web_search
        self._tool_registry = ToolRegistry()
        self._tool_registry.merge(self._graph_tools.build_registry())
        if hasattr(self._web_search, "build_registry"):
            self._tool_registry.merge(self._web_search.build_registry())  # type: ignore[arg-type]

    async def respond(
        self,
        *,
        user_id: str,
        message: str,
        model: str | None = None,
        session_id: str | None = None,
    ) -> AgentResponse:
        self._memory_service.ensure_user_anchor(user_id)
        self._memory_service.record_user_utterance(
            user_id=user_id,
            text=message,
            session_id=session_id,
        )

        memory_summary = self._graph_tools.get_user_memory_summary(user_id=user_id, limit=5)
        tool_history: list[dict] = []
        used_tools = ["memory.record_user_utterance", "graph.get_user_memory_summary"]
        memory_writes = ["user_utterance", "user_fact"]
        tool_events: list[dict] = []

        for _ in range(config.AGENT_MAX_TOOL_ROUNDS):
            turn = await self._chat_model.next_turn(
                system=SYSTEM_PROMPT,
                user_message=message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=self._tool_registry.definitions(),
                tool_history=tool_history,
            )
            if turn.final_answer:
                return AgentResponse(
                    text=turn.final_answer,
                    used_tools=used_tools,
                    memory_writes=memory_writes,
                    tool_events=tool_events,
                )
            if not turn.tool_calls:
                break
            for call in turn.tool_calls:
                result = await self._run_tool_call(call, user_id=user_id)
                used_tools.append(call.tool)
                if call.tool == "internet_search":
                    memory_writes.extend(["search_result", "search_fact"])
                event = {
                    "tool": call.tool,
                    "arguments": result["arguments"],
                    "result": result["result"],
                }
                tool_events.append(event)
                tool_history.append(event)

        return AgentResponse(
            text="도구 실행 이후에도 최종 응답을 만들지 못했습니다.",
            used_tools=used_tools,
            memory_writes=memory_writes,
            tool_events=tool_events,
        )

    def register_tool_registry(self, registry: ToolRegistry) -> None:
        self._tool_registry.merge(registry)

    async def _run_tool_call(self, call: ToolCall, *, user_id: str) -> dict:
        arguments = dict(call.arguments)
        if call.tool == "graph_search" and "user_id" not in arguments:
            arguments["user_id"] = user_id
        result = await self._tool_registry.run(ToolCall(tool=call.tool, arguments=arguments))
        if call.tool == "internet_search":
            query = str(arguments.get("query") or "").strip()
            hits = result.get("results")
            if query and isinstance(hits, list):
                self._memory_service.record_search_results(
                    query=query,
                    results=[item for item in hits if isinstance(item, dict)],
                )
        return {"arguments": arguments, "result": result}
