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
        self._active_graph_contexts: dict[str, list[str]] = {}

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
        previous_active_graph_context = list(self._active_graph_contexts.get(conversation_key, []))
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
        current_active_graph_context = self._initial_active_graph_context(
            user_id=user_id,
            utterance_id=utterance_id,
            memory_summary=memory_summary,
        )
        graph_activation_context = self._activate_graph_context(
            user_id=user_id,
            message=message,
            previous_active_graph_context=previous_active_graph_context,
            exclude_node_ids={utterance_id},
        )
        if graph_activation_context:
            used_tools.append("graph.active_context_activation")
            current_active_graph_context.extend(graph_activation_context)
        model_user_message = _compose_user_message(
            message=message,
            recent_messages=recent_messages,
            active_graph_context=previous_active_graph_context,
            graph_activation_context=graph_activation_context,
        )

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
            current_active_graph_context.extend(_active_context_from_tool_event(event))

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
                self._remember_active_graph_context(
                    conversation_key=conversation_key,
                    context=current_active_graph_context,
                )
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
                current_active_graph_context.extend(_active_context_from_tool_event(event))

        self._remember_user_message(conversation_key=conversation_key, message=message)
        self._remember_active_graph_context(
            conversation_key=conversation_key,
            context=current_active_graph_context,
        )
        return AgentResponse(
            text="도구 실행 이후에도 최종 응답을 만들지 못했습니다.",
            used_tools=used_tools,
            memory_writes=memory_writes,
            tool_events=tool_events,
        )

    def _remember_user_message(self, *, conversation_key: str, message: str) -> None:
        messages = [*self._recent_user_messages.get(conversation_key, []), message]
        self._recent_user_messages[conversation_key] = messages[-6:]

    def _remember_active_graph_context(self, *, conversation_key: str, context: list[str]) -> None:
        compacted: list[str] = []
        seen: set[str] = set()
        for item in context:
            normalized = " ".join(str(item).split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            compacted.append(normalized)
        self._active_graph_contexts[conversation_key] = compacted[-12:]

    def _initial_active_graph_context(
        self,
        *,
        user_id: str,
        utterance_id: str,
        memory_summary: list[str],
    ) -> list[str]:
        context = [f"current_utterance_node: {utterance_id}"]
        for label in self._memory_service.search_concept_nodes_for_utterance(
            user_id=user_id,
            utterance_id=utterance_id,
            limit=6,
        ):
            context.append(f"current_concept: {label}")
        for item in memory_summary[:5]:
            context.append(f"memory_summary: {item}")
        return context

    def _activate_graph_context(
        self,
        *,
        user_id: str,
        message: str,
        previous_active_graph_context: list[str],
        exclude_node_ids: set[str],
    ) -> list[str]:
        query_parts = [message.strip(), *previous_active_graph_context[-4:]]
        query = "\n".join(part for part in query_parts if part)
        if not query.strip():
            return []
        results = self._memory_service.graph_search(
            user_id=user_id,
            query=query,
            limit=6,
            exclude_node_ids=exclude_node_ids,
        )
        context: list[str] = []
        for item in results:
            node_type = str(item.get("node_type") or "").strip()
            node_id = str(item.get("node_id") or "").strip()
            label = _first_label(item)
            if label:
                context.append(f"activated_graph_node: {node_type} {label} ({node_id})")
            neighbors = item.get("neighbors")
            if isinstance(neighbors, list):
                for neighbor in neighbors[:2]:
                    if not isinstance(neighbor, dict):
                        continue
                    neighbor_label = _first_label(neighbor)
                    relation = str(neighbor.get("relation") or "").strip()
                    if neighbor_label and relation:
                        context.append(f"activated_graph_edge: {label} -[{relation}]- {neighbor_label}")
        return context[:12]

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


def _compose_user_message(
    *,
    message: str,
    recent_messages: list[str],
    active_graph_context: list[str],
    graph_activation_context: list[str],
) -> str:
    sections: list[str] = []
    if recent_messages:
        recent = "\n".join(f"- {item}" for item in recent_messages[-3:])
        sections.append(f"Recent user messages:\n{recent}")
    if active_graph_context:
        active = "\n".join(f"- {item}" for item in active_graph_context[-8:])
        sections.append(
            "Previous active graph context "
            "(recent working context; use only when relevant):\n"
            f"{active}"
        )
    if graph_activation_context:
        activated = "\n".join(f"- {item}" for item in graph_activation_context[-8:])
        sections.append(
            "Current graph activation "
            "(fresh graph retrieval for this turn; use only when relevant):\n"
            f"{activated}"
        )
    sections.append(f"Current user message:\n{message}")
    return "\n\n".join(sections)


def _active_context_from_tool_event(event: dict) -> list[str]:
    tool = str(event.get("tool") or "").strip()
    result = event.get("result")
    if not tool or not isinstance(result, dict):
        return []

    if tool == "graph_search":
        return _active_context_from_graph_search(result)
    if tool == "internet_search":
        return _active_context_from_internet_search(result)
    if tool == "workspace_file":
        return _active_context_from_workspace_file(result)
    if tool == "terminal_command":
        return _active_context_from_terminal_command(result)
    return []


def _active_context_from_graph_search(result: dict) -> list[str]:
    items = result.get("results")
    if not isinstance(items, list):
        return []
    context: list[str] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        node_type = str(item.get("node_type") or "").strip()
        label = _first_label(item)
        if label:
            context.append(f"graph_search_result: {node_type} {label} ({node_id})")
    return context


def _active_context_from_internet_search(result: dict) -> list[str]:
    context: list[str] = []
    nodes = result.get("search_nodes")
    if isinstance(nodes, list):
        for node in nodes[:6]:
            label = str(node).strip()
            if label:
                context.append(f"search_node: {label}")
    hits = result.get("results")
    if isinstance(hits, list):
        for item in hits[:4]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            source = str(item.get("source") or "").strip()
            query_node = str(item.get("query_node") or "").strip()
            if title:
                context.append(f"search_result: {title} [{source}] for {query_node}")
    return context


def _active_context_from_workspace_file(result: dict) -> list[str]:
    path = str(result.get("path") or "").strip()
    if not path:
        return []
    ok = result.get("ok")
    if ok is False:
        error = str(result.get("error") or "error").strip()
        return [f"workspace_file: {path} failed with {error}"]
    return [f"workspace_file: {path}"]


def _active_context_from_terminal_command(result: dict) -> list[str]:
    command = str(result.get("command") or "").strip()
    cwd = str(result.get("cwd") or "").strip()
    returncode = result.get("returncode")
    if not command:
        return []
    return [f"terminal_command: {command} cwd={cwd} returncode={returncode}"]


def _first_label(item: dict) -> str:
    labels = item.get("labels")
    if isinstance(labels, list) and labels:
        return str(labels[0]).strip()
    return ""
