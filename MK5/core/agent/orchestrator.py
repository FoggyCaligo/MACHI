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
        self._recent_user_messages: dict[str, list[str]] = {}

    async def respond(
        self,
        *,
        user_id: str,
        message: str,
        model: str | None = None,
        session_id: str | None = None,
    ) -> AgentResponse:
        self._memory_service.ensure_user_anchor(user_id)
        conversation_key = f"{user_id}::{session_id or 'default'}"
        recent_messages = list(self._recent_user_messages.get(conversation_key, []))
        utterance_id = self._memory_service.record_user_utterance(
            user_id=user_id,
            text=message,
            session_id=session_id,
        )

        memory_summary = self._graph_tools.get_user_memory_summary(
            user_id=user_id,
            query=message,
            limit=5,
            exclude_node_ids={utterance_id},
        )
        tool_history: list[dict] = []
        used_tools = ["memory.record_user_utterance", "graph.get_user_memory_summary"]
        memory_writes = ["user_utterance", "user_fact"]
        tool_events: list[dict] = []
        model_user_message = _compose_user_message(message=message, recent_messages=recent_messages)

        if (
            not memory_summary
            and self._memory_service.should_search_without_slots(user_id=user_id, utterance_id=utterance_id)
        ):
            result = await self._run_tool_call(
                ToolCall(tool="internet_search", arguments={"query": message}),
                user_id=user_id,
                utterance_id=utterance_id,
            )
            used_tools.append("internet_search")
            memory_writes.extend(["search_result", "search_fact"])
            event = {
                "tool": "internet_search",
                "arguments": result["arguments"],
                "result": result["result"],
            }
            tool_events.append(event)
            tool_history.append(event)

        for _ in range(config.AGENT_MAX_TOOL_ROUNDS):
            turn = await self._chat_model.next_turn(
                system=SYSTEM_PROMPT,
                user_message=model_user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=self._tool_registry.definitions(),
                tool_history=tool_history,
            )
            if turn.final_answer:
                self._remember_user_message(conversation_key=conversation_key, message=message)
                return AgentResponse(
                    text=turn.final_answer,
                    used_tools=used_tools,
                    memory_writes=memory_writes,
                    tool_events=tool_events,
                )
            if not turn.tool_calls:
                break
            for call in turn.tool_calls:
                result = await self._run_tool_call(call, user_id=user_id, utterance_id=utterance_id)
                used_tools.append(call.tool)
                if call.tool == "internet_search":
                    memory_writes.extend(["search_result", "search_fact"])
                elif call.tool == "record_memory_correction":
                    memory_writes.append("user_fact_correction")
                elif call.tool == "workspace_file":
                    memory_writes.append("workspace_file")
                event = {
                    "tool": call.tool,
                    "arguments": result["arguments"],
                    "result": result["result"],
                }
                tool_events.append(event)
                tool_history.append(event)

        self._remember_user_message(conversation_key=conversation_key, message=message)
        return AgentResponse(
            text="도구 실행 이후에도 최종 응답을 만들지 못했습니다.",
            used_tools=used_tools,
            memory_writes=memory_writes,
            tool_events=tool_events,
        )

    def _remember_user_message(self, *, conversation_key: str, message: str) -> None:
        messages = [*self._recent_user_messages.get(conversation_key, []), message]
        self._recent_user_messages[conversation_key] = messages[-6:]

    def register_tool_registry(self, registry: ToolRegistry) -> None:
        self._tool_registry.merge(registry)

    async def _run_tool_call(self, call: ToolCall, *, user_id: str, utterance_id: str) -> dict:
        arguments = dict(call.arguments)
        if call.tool in {"graph_search", "record_memory_correction"} and "user_id" not in arguments:
            arguments["user_id"] = user_id
        if call.tool == "internet_search" and "search_nodes" not in arguments:
            search_nodes = self._memory_service.search_concept_nodes_for_utterance(
                user_id=user_id,
                utterance_id=utterance_id,
            )
            if search_nodes:
                arguments["search_nodes"] = search_nodes
        result = await self._tool_registry.run(ToolCall(tool=call.tool, arguments=arguments))
        if call.tool == "internet_search":
            self._persist_search_results(arguments=arguments, result=result)
        return {"arguments": arguments, "result": result}

    def _persist_search_results(self, *, arguments: dict, result: dict) -> None:
        query = str(arguments.get("query") or "").strip()
        hits = result.get("results")
        if not query or not isinstance(hits, list):
            return

        grouped: dict[str, list[dict]] = {}
        for item in hits:
            if not isinstance(item, dict):
                continue
            query_node = str(item.get("query_node") or query).strip() or query
            grouped.setdefault(query_node, []).append(item)
        for query_node, node_hits in grouped.items():
            self._memory_service.record_search_results(query=query_node, results=node_hits)


def _compose_user_message(*, message: str, recent_messages: list[str]) -> str:
    if not recent_messages:
        return message
    recent = "\n".join(f"- {item}" for item in recent_messages[-3:])
    return f"Recent user messages:\n{recent}\n\nCurrent user message:\n{message}"
