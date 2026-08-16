from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re
import sys
import time

from ... import config
from ...tools.graph_tools import GraphToolSuite
from ...tools.llm_client import ChatModel, ModelTurn
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
        self._recent_dialogue_messages: dict[str, list[str]] = {}
        self._previous_activation_node_ids: dict[str, set[str]] = {}
        self._recent_file_operations: dict[str, list[dict]] = {}
        self._recent_tool_operations: dict[str, list[dict]] = {}
        self._auto_read_attachment_paths: dict[str, set[str]] = {}

    async def respond(
        self,
        *,
        user_id: str,
        message: str,
        model: str | None = None,
        image_model: str | None = None,
        session_id: str | None = None,
    ) -> AgentResponse:
        self._memory_service.ensure_user_anchor(user_id)
        conversation_key = f"{user_id}::{session_id or 'default'}"
        recent_dialogue_messages = list(self._recent_dialogue_messages.get(conversation_key, []))
        recent_file_operations = list(self._recent_file_operations.get(conversation_key, []))
        recent_tool_operations = list(self._recent_tool_operations.get(conversation_key, []))
        previous_activation_node_ids = set(self._previous_activation_node_ids.get(conversation_key, set()))
        utterance_id = self._memory_service.record_user_utterance(
            user_id=user_id,
            text=message,
            session_id=session_id,
        )
        local_activation_node_ids = self._memory_service.local_activation_node_ids_for_utterance(
            user_id=user_id,
            utterance_id=utterance_id,
            previous_activation_node_ids=previous_activation_node_ids,
        )
        local_activation_node_weights = self._memory_service.local_activation_node_weights_for_utterance(
            user_id=user_id,
            utterance_id=utterance_id,
            previous_activation_node_ids=previous_activation_node_ids,
            previous_weight=0.5,
        )

        memory_summary = self._graph_tools.get_user_memory_summary(
            user_id=user_id,
            query=message,
            limit=config.MEMORY_SUMMARY_LIMIT,
            exclude_node_ids={utterance_id},
            activation_node_weights=local_activation_node_weights,
        )
        tool_history: list[dict] = []
        used_tools = ["memory.record_user_utterance", "graph.get_user_memory_summary"]
        memory_writes = ["user_utterance", "user_fact"]
        tool_events: list[dict] = []
        auto_read_attachment_paths = self._auto_read_attachment_paths.setdefault(conversation_key, set())
        auto_attachment_calls = [
            call
            for call in _auto_file_tool_calls(message)
            if str(call.arguments.get("path") or "") not in auto_read_attachment_paths
        ][: max(0, config.AUTO_ATTACHMENT_TOOL_LIMIT)]
        for attachment_call in auto_attachment_calls:
            if not self._tool_registry.has_tool(attachment_call.tool):
                continue
            _debug_log(f"auto_tool_start tool={attachment_call.tool} reason=attachment")
            started = time.perf_counter()
            result = await self._run_tool_call(
                attachment_call,
                user_id=user_id,
                utterance_id=utterance_id,
                image_model=image_model,
            )
            _debug_log(
                f"auto_tool_end tool={attachment_call.tool} reason=attachment "
                f"elapsed={time.perf_counter() - started:.2f}s ok={_tool_ok(result.get('result'))}"
            )
            used_tools.append(attachment_call.tool)
            event = {
                "tool": attachment_call.tool,
                "arguments": result["arguments"],
                "result": result["result"],
            }
            tool_events.append(event)
            tool_history.append(event)
            path = str(result["arguments"].get("path") or "")
            if path:
                auto_read_attachment_paths.add(path)
        model_user_message = _compose_user_message(
            message=message,
            recent_dialogue_messages=recent_dialogue_messages,
            recent_file_operations=recent_file_operations,
            recent_tool_operations=recent_tool_operations,
        )

        if (
            not memory_summary
            and self._memory_service.should_search_without_slots(user_id=user_id, utterance_id=utterance_id)
        ):
            _debug_log("auto_tool_start tool=internet_search")
            started = time.perf_counter()
            result = await self._run_tool_call(
                ToolCall(tool="internet_search", arguments={"query": message}),
                user_id=user_id,
                utterance_id=utterance_id,
                image_model=image_model,
            )
            _debug_log(f"auto_tool_end tool=internet_search elapsed={time.perf_counter() - started:.2f}s")
            used_tools.append("internet_search")
            memory_writes.extend(["search_result", "search_fact"])
            event = {
                "tool": "internet_search",
                "arguments": result["arguments"],
                "result": result["result"],
            }
            tool_events.append(event)
            tool_history.append(event)

        for round_index in range(1, config.AGENT_MAX_TOOL_ROUNDS + 1):
            _debug_log(
                f"model_round_start round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                f"tool_history={len(tool_history)}"
            )
            started = time.perf_counter()
            try:
                turn = await self._chat_model.next_turn(
                    system=SYSTEM_PROMPT,
                    user_message=model_user_message,
                    model=model,
                    memory_summary=memory_summary,
                    tool_definitions=self._tool_registry.definitions(),
                    tool_history=tool_history,
                )
            except (RuntimeError, ValueError) as exc:
                guard_result = _model_output_guard_result(exc)
                _debug_log(
                    f"model_round_error round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                    f"elapsed={time.perf_counter() - started:.2f}s "
                    f"error={guard_result.get('error')}"
                )
                tool_history.append({
                    "tool": "execution_guard",
                    "arguments": {},
                    "result": guard_result,
                })
                continue
            _debug_log(
                f"model_round_end round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                f"elapsed={time.perf_counter() - started:.2f}s "
                f"final={bool(turn.final_answer)} tool_calls={len(turn.tool_calls)}"
            )
            if turn.final_answer and turn.tool_calls:
                if all(
                    _has_successful_tool_event(tool_history, call.tool, arguments=call.arguments)
                    for call in turn.tool_calls
                ):
                    _debug_log(
                        f"mixed_model_turn round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                        "action=use_final_ignore_duplicate_tool_calls"
                    )
                else:
                    _debug_log(
                        f"mixed_model_turn round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                        "action=run_tool_calls_ignore_final"
                    )
                    turn = ModelTurn(tool_calls=turn.tool_calls)
            if turn.final_answer:
                guard_result = _final_answer_evidence_guard_result(
                    turn=turn,
                    tool_history=tool_history,
                    rejected_final_answer=turn.final_answer,
                ) or _file_execution_guard_result(
                    tool_history=tool_history,
                    rejected_final_answer=turn.final_answer,
                )
                if guard_result is not None:
                    _debug_log(
                        f"execution_guard round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                        f"error={guard_result.get('error')}"
                    )
                    tool_history.append({
                        "tool": "execution_guard",
                        "arguments": {},
                        "result": guard_result,
                    })
                    continue
                self._remember_dialogue_messages(
                    conversation_key=conversation_key,
                    user_message=message,
                    assistant_message=turn.final_answer,
                )
                self._remember_activation_node_ids(
                    conversation_key=conversation_key,
                    node_ids=local_activation_node_ids,
                )
                self._remember_file_operations(
                    conversation_key=conversation_key,
                    tool_events=tool_events,
                )
                self._remember_tool_operations(
                    conversation_key=conversation_key,
                    tool_events=tool_events,
                    tool_history=tool_history,
                )
                return AgentResponse(
                    text=turn.final_answer,
                    used_tools=used_tools,
                    memory_writes=memory_writes,
                    tool_events=tool_events,
                )
            if not turn.tool_calls:
                guard_result = _empty_turn_after_tool_guard_result(tool_history=tool_history)
                _debug_log(
                    f"execution_guard round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                    f"error={guard_result.get('error')}"
                )
                tool_history.append({
                    "tool": "execution_guard",
                    "arguments": {},
                    "result": guard_result,
                })
                continue
            unknown_tool_call = next(
                (call for call in turn.tool_calls if not self._tool_registry.has_tool(call.tool)),
                None,
            )
            if unknown_tool_call is not None:
                guard_result = _unknown_tool_guard_result(
                    unknown_tool=unknown_tool_call.tool,
                    available_tools=[definition.name for definition in self._tool_registry.definitions()],
                )
                _debug_log(
                    f"execution_guard round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                    f"error={guard_result.get('error')} unknown_tool={unknown_tool_call.tool}"
                )
                tool_history.append({
                    "tool": "execution_guard",
                    "arguments": {},
                    "result": guard_result,
                })
                continue
            for call in turn.tool_calls:
                _debug_log(f"tool_start round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} tool={call.tool}")
                started = time.perf_counter()
                result = await self._run_tool_call(
                    call,
                    user_id=user_id,
                    utterance_id=utterance_id,
                    image_model=image_model,
                )
                _debug_log(
                    f"tool_end round={round_index}/{config.AGENT_MAX_TOOL_ROUNDS} "
                    f"tool={call.tool} elapsed={time.perf_counter() - started:.2f}s "
                    f"ok={_tool_ok(result.get('result'))}"
                )
                used_tools.append(call.tool)
                if call.tool in {"internet_search", "latest_search"}:
                    memory_writes.extend(["search_result", "search_fact"])
                elif call.tool == "market_snapshot":
                    memory_writes.append("market_snapshot")
                elif call.tool == "record_memory_correction":
                    memory_writes.append("user_fact_correction")
                elif call.tool in {"file_create", "file_read", "file_update", "file_delete"}:
                    memory_writes.append(call.tool)
                event = {
                    "tool": call.tool,
                    "arguments": result["arguments"],
                    "result": result["result"],
                }
                tool_events.append(event)
                tool_history.append(event)

        fallback_answer = "도구 실행 이후에도 최종 답변을 만들지 못했습니다."
        self._remember_dialogue_messages(
            conversation_key=conversation_key,
            user_message=message,
            assistant_message=fallback_answer,
        )
        self._remember_activation_node_ids(
            conversation_key=conversation_key,
            node_ids=local_activation_node_ids,
        )
        self._remember_file_operations(
            conversation_key=conversation_key,
            tool_events=tool_events,
        )
        self._remember_tool_operations(
            conversation_key=conversation_key,
            tool_events=tool_events,
            tool_history=tool_history,
        )
        return AgentResponse(
            text=fallback_answer,
            used_tools=used_tools,
            memory_writes=memory_writes,
            tool_events=tool_events,
        )

    def _remember_dialogue_messages(
        self,
        *,
        conversation_key: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        existing = list(self._recent_dialogue_messages.get(conversation_key, []))
        updated = [
            *existing,
            f"User: {user_message}",
            f"Assistant: {assistant_message}",
        ]
        limit = max(0, config.RECENT_MESSAGE_LIMIT)
        self._recent_dialogue_messages[conversation_key] = updated[-limit:] if limit else []

    def _remember_activation_node_ids(self, *, conversation_key: str, node_ids: set[str]) -> None:
        self._previous_activation_node_ids[conversation_key] = set(node_ids)

    def _remember_file_operations(self, *, conversation_key: str, tool_events: list[dict]) -> None:
        operations = [_file_operation_context(event) for event in tool_events]
        self._recent_file_operations[conversation_key] = [item for item in operations if item is not None][-3:]

    def _remember_tool_operations(
        self,
        *,
        conversation_key: str,
        tool_events: list[dict],
        tool_history: list[dict],
    ) -> None:
        operations = [_tool_operation_context(event) for event in [*tool_events, *tool_history]]
        deduped: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for item in operations:
            if item is None:
                continue
            key = (str(item.get("tool")), str(item.get("arguments")), str(item.get("result_summary")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        if deduped:
            self._recent_tool_operations[conversation_key] = deduped[-5:]

    def register_tool_registry(self, registry: ToolRegistry) -> None:
        self._tool_registry.merge(registry)

    async def _run_tool_call(
        self,
        call: ToolCall,
        *,
        user_id: str,
        utterance_id: str,
        image_model: str | None = None,
    ) -> dict:
        arguments = dict(call.arguments)
        if call.tool in {"graph_search", "record_memory_correction"} and "user_id" not in arguments:
            arguments["user_id"] = user_id
        if call.tool == "image_analyze" and image_model and not str(arguments.get("model") or "").strip():
            arguments["model"] = image_model
        if call.tool in {"internet_search", "latest_search"} and "search_nodes" not in arguments:
            search_nodes = self._memory_service.search_concept_nodes_for_utterance(
                user_id=user_id,
                utterance_id=utterance_id,
            )
            if search_nodes:
                arguments["search_nodes"] = search_nodes
        result = await self._tool_registry.run(ToolCall(tool=call.tool, arguments=arguments))
        if call.tool in {"internet_search", "latest_search"}:
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


def _auto_file_tool_calls(message: str) -> list[ToolCall]:
    calls = [*_attachment_tool_calls(message), *_mentioned_image_tool_calls(message)]
    deduped: list[ToolCall] = []
    seen: set[tuple[str, str]] = set()
    for call in calls:
        path = str(call.arguments.get("path") or "")
        key = (call.tool, path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(call)
    return deduped


def _attachment_tool_calls(message: str) -> list[ToolCall]:
    if "[첨부 파일]" not in message:
        return []
    paths: list[str] = []
    in_attachment_section = False
    for line in message.splitlines():
        stripped = line.strip()
        if stripped == "[첨부 파일]":
            in_attachment_section = True
            continue
        if in_attachment_section and stripped.startswith("[") and stripped.endswith("]"):
            break
        if not in_attachment_section or not stripped.startswith("- "):
            continue
        match = re.match(r"-\s+.*?:\s+(.+)$", stripped)
        if match:
            paths.append(match.group(1).strip())

    calls: list[ToolCall] = []
    for path in paths:
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            calls.append(ToolCall(tool="image_analyze", arguments={"path": path}))
        elif suffix in {".pdf", ".docx"}:
            calls.append(ToolCall(tool="document_read", arguments={"path": path}))
        else:
            calls.append(ToolCall(tool="file_read", arguments={"path": path}))
    return calls


def _mentioned_image_tool_calls(message: str) -> list[ToolCall]:
    if "[첨부 파일]" in message:
        head = message.split("[첨부 파일]", 1)[0]
    else:
        head = message
    paths = re.findall(r"([^\s`'\"<>:]+?\.(?:png|jpg|jpeg|webp|bmp|gif))", head, re.IGNORECASE)
    return [ToolCall(tool="image_analyze", arguments={"path": path}) for path in paths]


def _compose_user_message(
    *,
    message: str,
    recent_dialogue_messages: list[str],
    recent_file_operations: list[dict],
    recent_tool_operations: list[dict],
) -> str:
    sections: list[str] = []
    if recent_dialogue_messages:
        dialogue = "\n".join(f"- {item}" for item in recent_dialogue_messages)
        sections.append(f"Previous dialogue turn:\n{dialogue}")
    if recent_file_operations:
        lines = []
        for item in recent_file_operations:
            lines.append(
                "- "
                f"tool={item.get('tool')} "
                f"path={item.get('path')} "
                f"ok={item.get('ok')} "
                f"mode={item.get('mode')} "
                f"old={item.get('old')!r} "
                f"new={item.get('new')!r} "
                f"content_tail={item.get('content_tail')!r}"
            )
        sections.append("Previous file operation:\n" + "\n".join(lines))
    if recent_tool_operations:
        lines = []
        for item in recent_tool_operations:
            lines.append(
                "- "
                f"tool={item.get('tool')} "
                f"arguments={item.get('arguments')!r} "
                f"ok={item.get('ok')!r} "
                f"returncode={item.get('returncode')!r} "
                f"error={item.get('error')!r} "
                f"result_summary={item.get('result_summary')!r}"
            )
        sections.append("Previous tool operation:\n" + "\n".join(lines))
    sections.append(f"Current user message:\n{message}")
    return "\n\n".join(sections)


def _file_operation_context(event: dict) -> dict | None:
    if event.get("tool") not in {"file_create", "file_read", "file_update", "file_delete"}:
        return None
    arguments = event.get("arguments")
    result = event.get("result")
    if not isinstance(arguments, dict) or not isinstance(result, dict):
        return None
    content = str(arguments.get("content") or result.get("content") or "")
    return {
        "tool": event.get("tool"),
        "path": arguments.get("path") or result.get("path"),
        "ok": result.get("ok"),
        "mode": result.get("mode"),
        "old": arguments.get("old"),
        "new": arguments.get("new"),
        "content_tail": content[-200:] if content else "",
    }


def _tool_operation_context(event: dict) -> dict | None:
    tool = event.get("tool")
    if tool in {None, "execution_guard"}:
        return None
    arguments = event.get("arguments")
    result = event.get("result")
    if not isinstance(arguments, dict) or not isinstance(result, dict):
        return None
    return {
        "tool": tool,
        "arguments": _compact_mapping(arguments),
        "ok": result.get("ok"),
        "returncode": result.get("returncode"),
        "error": result.get("error"),
        "result_summary": _tool_result_summary(tool=str(tool), result=result),
    }


def _compact_mapping(value: dict) -> dict:
    compact: dict = {}
    for key, item in value.items():
        text = str(item)
        compact[key] = text if len(text) <= 180 else text[:177] + "..."
    return compact


def _tool_result_summary(*, tool: str, result: dict) -> str:
    if tool == "terminal_command":
        parts = []
        stdout = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        if stdout:
            parts.append(f"stdout={_truncate(stdout, 240)!r}")
        if stderr:
            parts.append(f"stderr={_truncate(stderr, 240)!r}")
        if result.get("changed_paths"):
            parts.append(f"changed_paths={result.get('changed_paths')!r}")
        return " ".join(parts)
    if tool in {"file_read", "document_read"}:
        content = str(result.get("content") or "")
        return f"path={result.get('path')!r} content_tail={_truncate(content[-240:], 240)!r}"
    if tool == "image_analyze":
        description = str(result.get("description") or result.get("message") or "")
        return f"path={result.get('path')!r} image={result.get('image')!r} description={_truncate(description, 240)!r}"
    return _truncate(str(result), 240)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _tool_ok(result: object) -> object:
    if not isinstance(result, dict):
        return None
    if "ok" in result:
        return result.get("ok")
    if "returncode" in result:
        return result.get("returncode") == 0
    return None


def _debug_log(message: str) -> None:
    if not config.AGENT_DEBUG_LOG:
        return
    print(f"[MK5 agent] {message}", file=sys.stderr, flush=True)


def _model_output_guard_result(exc: Exception) -> dict:
    return {
        "ok": False,
        "error": "model_output_parse_failed",
        "message": (
            "The previous model response could not be parsed as the required JSON object. "
            "Return valid JSON only. If the task requires creating or running a script, "
            "use tool_calls such as file_create and terminal_command with final_answer set "
            "to null. Do not put raw code or unescaped multiline text directly outside JSON."
        ),
        "exception": _truncate(str(exc), 500),
    }


def _has_file_execution_event(tool_history: list[dict]) -> bool:
    return any(
        event.get("tool") in {"file_create", "file_read", "file_update", "file_delete", "terminal_command"}
        for event in tool_history
    )


def _has_successful_tool_event(
    tool_history: list[dict],
    tool_name: str,
    *,
    arguments: dict | None = None,
) -> bool:
    for event in tool_history:
        if event.get("tool") != tool_name:
            continue
        if arguments is not None and not _arguments_include(event.get("arguments"), arguments):
            continue
        result = event.get("result")
        if isinstance(result, dict):
            if result.get("ok") is False:
                continue
            if "returncode" in result and result.get("returncode") != 0:
                continue
        return True
    return False


def _arguments_include(actual: object, expected_subset: dict) -> bool:
    if not isinstance(actual, dict):
        return False
    return all(actual.get(key) == value for key, value in expected_subset.items())


def _has_successful_file_mutation_event(tool_history: list[dict]) -> bool:
    for event in tool_history:
        if event.get("tool") not in {"file_create", "file_update", "file_delete"}:
            continue
        result = event.get("result")
        if isinstance(result, dict) and result.get("ok") is True:
            return True
    return False


def _has_failed_file_mutation_event(tool_history: list[dict]) -> bool:
    for event in reversed(tool_history):
        if event.get("tool") not in {"file_create", "file_update", "file_delete"}:
            continue
        result = event.get("result")
        return not isinstance(result, dict) or result.get("ok") is not True
    return False


def _has_terminal_filesystem_change_without_verification(tool_history: list[dict]) -> bool:
    latest_change_index: int | None = None
    for index, event in enumerate(tool_history):
        result = event.get("result")
        if (
            event.get("tool") == "terminal_command"
            and isinstance(result, dict)
            and result.get("filesystem_changed") is True
        ):
            latest_change_index = index
    if latest_change_index is None:
        return False
    for event in tool_history[latest_change_index + 1:]:
        result = event.get("result")
        if event.get("tool") == "file_read" and isinstance(result, dict) and result.get("ok") is True:
            return False
        if event.get("tool") in {"file_create", "file_update", "file_delete"} and isinstance(result, dict) and result.get("ok") is True:
            return False
    return True


def _file_execution_guard_result(
    *,
    tool_history: list[dict],
    rejected_final_answer: str,
) -> dict | None:
    if _has_failed_file_mutation_event(tool_history):
        return {
            "ok": False,
            "error": "file_mutation_failed",
            "message": (
                "A file mutation tool was called, but it did not return ok=true. "
                "Do not report completion until a file_create, file_update, or file_delete "
                "tool succeeds, or explain the blocker."
            ),
            "rejected_final_answer": rejected_final_answer,
        }
    if _has_terminal_filesystem_change_without_verification(tool_history):
        return {
            "ok": False,
            "error": "terminal_filesystem_change_not_verified",
            "message": (
                "A terminal_command changed the filesystem. Verify the affected file with "
                "file_read, or use a successful file_create, file_update, or file_delete "
                "before reporting completion."
            ),
            "rejected_final_answer": rejected_final_answer,
        }
    return None


def _empty_turn_after_tool_guard_result(*, tool_history: list[dict]) -> dict:
    latest_tool = tool_history[-1].get("tool") if tool_history else None
    latest_result = tool_history[-1].get("result") if tool_history else None
    if not tool_history:
        return {
            "ok": False,
            "error": "empty_initial_turn",
            "message": (
                "The model returned neither final_answer nor tool_calls on the first round. "
                "Continue by returning the needed tool_calls, a final_answer, or a blocker explanation."
            ),
        }
    if (
        latest_tool in {"file_create", "file_update", "file_delete"}
        and isinstance(latest_result, dict)
        and latest_result.get("ok") is not True
    ):
        return {
            "ok": False,
            "error": "empty_turn_after_failed_file_mutation",
            "message": (
                "The last file mutation failed. Read the error message in tool_history, "
                "retry with corrected arguments when possible, or return a blocker explanation. "
                "For file_update exact replacement, use only path, old, and new. For append, "
                "use only path, mode='append', and content. For full overwrite, use only path and content."
            ),
        }
    if latest_tool in {"file_read", "document_read", "image_analyze"}:
        return {
            "ok": False,
            "error": f"empty_turn_after_{latest_tool}",
            "message": (
                f"A {latest_tool} result is available, but the model returned neither "
                "final_answer nor tool_calls. Use the available content to continue with "
                "the requested operation, or return a blocker explanation."
            ),
        }
    return {
        "ok": False,
        "error": "empty_turn_after_tool",
        "message": (
            "A tool result is available, but the model returned neither final_answer nor "
            "tool_calls. Continue from tool_history with the next needed tool call, final "
            "answer, or blocker explanation."
        ),
    }


def _unknown_tool_guard_result(*, unknown_tool: str, available_tools: list[str]) -> dict:
    if unknown_tool == "final_answer":
        message = (
            "final_answer is not a tool. Put the answer in the top-level final_answer "
            "field with tool_calls=[], or call one of the available tools if more work is needed."
        )
    else:
        message = (
            f"{unknown_tool} is not an available tool. Use one of the available tools, "
            "or return a top-level final_answer if no tool is needed."
        )
    return {
        "ok": False,
        "error": "unknown_tool_call",
        "unknown_tool": unknown_tool,
        "available_tools": available_tools,
        "message": message,
    }


def _final_answer_evidence_guard_result(
    *,
    turn: ModelTurn,
    tool_history: list[dict],
    rejected_final_answer: str,
) -> dict | None:
    if turn.final_answer_kind != "tool_completion":
        return None
    if not turn.completion_tools:
        return {
            "ok": False,
            "error": "missing_completion_tools",
            "message": (
                "The final answer claims a completed tool-backed action, but completion_tools "
                "is empty. List the tool names that support the completion, or call the needed "
                "tool before reporting completion."
            ),
            "rejected_final_answer": rejected_final_answer,
        }
    missing_tools = [
        tool_name
        for tool_name in turn.completion_tools
        if not _has_successful_tool_event(tool_history, tool_name)
    ]
    if missing_tools:
        return {
            "ok": False,
            "error": "completion_tool_not_run",
            "message": (
                "The final answer claims a completed tool-backed action, but these supporting "
                f"tools have not succeeded in tool_history: {missing_tools}. Call the needed "
                "tool first, or explain the blocker."
            ),
            "missing_tools": missing_tools,
            "rejected_final_answer": rejected_final_answer,
        }
    return None

