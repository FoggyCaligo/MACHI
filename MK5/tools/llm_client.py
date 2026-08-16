from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from .ollama_client import chat as ollama_chat
from .tool_runtime import ToolCall, ToolDefinition


@dataclass(slots=True)
class ModelTurn:
    final_answer: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_answer_kind: str = "answer"
    completion_tools: list[str] = field(default_factory=list)


class ChatModel(Protocol):
    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn: ...


_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "final_answer": {"type": ["string", "null"]},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["tool", "arguments"],
                "additionalProperties": False,
            },
        },
        "final_answer_kind": {
            "type": "string",
            "enum": ["answer", "tool_completion", "blocked"],
        },
        "completion_tools": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["final_answer", "tool_calls", "final_answer_kind", "completion_tools"],
    "additionalProperties": False,
}


def _parse_model_turn(raw: str) -> ModelTurn:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        extracted = _extract_braced_json(raw)
        if extracted:
            try:
                data = json.loads(extracted)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Model response must be valid JSON with final_answer and tool_calls: {exc}"
                ) from exc
        else:
            raise RuntimeError("Model response must be JSON with final_answer and tool_calls.")
    if not isinstance(data, dict):
        raise RuntimeError("Model response must be a JSON object.")
    final_answer = data.get("final_answer")
    if final_answer is not None and not isinstance(final_answer, str):
        raise RuntimeError("final_answer must be string or null.")
    tool_calls_raw = data.get("tool_calls")
    if not isinstance(tool_calls_raw, list):
        raise RuntimeError("tool_calls must be a list.")
    final_answer_kind = data.get("final_answer_kind", "answer")
    if final_answer_kind not in {"answer", "tool_completion", "blocked"}:
        raise RuntimeError("final_answer_kind must be answer, tool_completion, or blocked.")
    completion_tools_raw = data.get("completion_tools", [])
    if not isinstance(completion_tools_raw, list) or not all(
        isinstance(item, str) for item in completion_tools_raw
    ):
        raise RuntimeError("completion_tools must be a list of strings.")

    tool_calls: list[ToolCall] = []
    for idx, item in enumerate(tool_calls_raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"tool_calls[{idx}] must be an object.")
        tool = item.get("tool")
        arguments = item.get("arguments")
        if not isinstance(tool, str) or not tool.strip():
            raise RuntimeError(f"tool_calls[{idx}].tool must be a non-empty string.")
        if not isinstance(arguments, dict):
            raise RuntimeError(f"tool_calls[{idx}].arguments must be an object.")
        tool_calls.append(ToolCall(tool=tool.strip(), arguments=arguments))
    return ModelTurn(
        final_answer=final_answer.strip() if isinstance(final_answer, str) else None,
        tool_calls=tool_calls,
        final_answer_kind=final_answer_kind,
        completion_tools=[item.strip() for item in completion_tools_raw if item.strip()],
    )


def _extract_braced_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start:end + 1]


class OllamaToolChatModel:
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
        tool_spec_payload = [_compact_tool_definition(tool) for tool in tool_definitions]
        user_payload = {
            "user_message": user_message,
            "memory_summary": memory_summary,
            "tools": tool_spec_payload,
            "tool_history": [_compact_tool_history_event(event) for event in tool_history],
            "output_contract": {
                "final_answer": "string|null",
                "tool_calls": [{"tool": "name", "arguments": {}}],
                "final_answer_kind": "answer | tool_completion | blocked",
                "completion_tools": ["required when final_answer_kind=tool_completion"],
            },
        }
        raw = await ollama_chat(
            system=system,
            user=json.dumps(user_payload, ensure_ascii=False),
            model=model,
            response_format=_RESPONSE_SCHEMA,
        )
        return _parse_model_turn(raw)


class StubChatModel:
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
        if not tool_history and "search" in user_message.lower():
            return ModelTurn(
                tool_calls=[ToolCall(tool="internet_search", arguments={"query": user_message})]
            )
        if memory_summary:
            return ModelTurn(final_answer=f"MK5 stub reply.\nmessage={user_message}\nmemory={memory_summary}")
        return ModelTurn(final_answer=f"MK5 stub reply.\nmessage={user_message}")


def _compact_tool_definition(tool: ToolDefinition) -> dict[str, Any]:
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    properties = schema.get("properties")
    required = schema.get("required")
    argument_keys = sorted(properties) if isinstance(properties, dict) else _argument_keys_from_variants(schema)
    compact = {
        "name": tool.name,
        "description": _shorten(tool.description, 120),
        "arguments": argument_keys,
        "required": required if isinstance(required, list) else [],
    }
    if tool.name != "tool_manual":
        compact["manual"] = f"tool_manual:{tool.name}"
    variants = _argument_variants(schema)
    if variants:
        compact["argument_shapes"] = variants
    return compact


def _argument_keys_from_variants(schema: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    for variant in schema.get("oneOf") or schema.get("anyOf") or []:
        if not isinstance(variant, dict):
            continue
        properties = variant.get("properties")
        if isinstance(properties, dict):
            keys.update(str(key) for key in properties)
    return sorted(keys)


def _argument_variants(schema: dict[str, Any]) -> list[list[str]]:
    variants: list[list[str]] = []
    for variant in schema.get("oneOf") or schema.get("anyOf") or []:
        if not isinstance(variant, dict):
            continue
        required = variant.get("required")
        if isinstance(required, list):
            variants.append([str(item) for item in required])
    return variants


def _compact_tool_history_event(event: dict[str, Any]) -> dict[str, Any]:
    tool = event.get("tool")
    arguments = event.get("arguments")
    result = event.get("result")
    return {
        "tool": tool,
        "arguments": _compact_value(arguments, limit=180),
        "result": _compact_tool_result(tool=tool, result=result),
    }


def _compact_tool_result(*, tool: object, result: object) -> object:
    if not isinstance(result, dict):
        return _compact_value(result, limit=240)
    compact: dict[str, Any] = {}
    for key in ("ok", "error", "status", "mode", "path", "returncode", "freshness", "query"):
        if key in result:
            compact[key] = result.get(key)
    if tool == "terminal_command":
        _add_tail(compact, "stdout", result.get("stdout"), 320)
        _add_tail(compact, "stderr", result.get("stderr"), 320)
        if result.get("changed_paths"):
            compact["changed_paths"] = _compact_value(result.get("changed_paths"), limit=240)
    elif tool in {"file_read", "document_read"}:
        _add_tail(compact, "content", result.get("content"), 500)
    elif tool == "image_analyze":
        if "image" in result:
            compact["image"] = result.get("image")
        _add_tail(compact, "description", result.get("description") or result.get("message"), 500)
        if result.get("vision_model_used"):
            compact["vision_model_used"] = result.get("vision_model_used")
    elif tool in {"internet_search", "latest_search"}:
        results = result.get("results")
        if isinstance(results, list):
            compact["result_count"] = len(results)
            compact["results"] = [_compact_search_result(item) for item in results[:5]]
        source_errors = result.get("source_errors")
        if source_errors:
            compact["source_errors"] = _compact_value(source_errors, limit=300)
    elif tool == "market_snapshot":
        compact["snapshot"] = _compact_value(result, limit=700)
    elif tool == "file_text_activation":
        compact["context_node_id"] = result.get("context_node_id")
        compact["activation_weight"] = result.get("activation_weight")
        compact["retention"] = result.get("retention")
        compact["nodes"] = _compact_value(result.get("nodes"), limit=500)
    elif tool == "execution_guard":
        compact["message"] = _shorten(str(result.get("message") or ""), 240)
        if result.get("missing_tools"):
            compact["missing_tools"] = result.get("missing_tools")
        if result.get("unknown_tool"):
            compact["unknown_tool"] = result.get("unknown_tool")
    elif tool == "tool_manual":
        compact["tool"] = result.get("tool")
        compact["description"] = _shorten(str(result.get("description") or ""), 300)
        input_schema = result.get("input_schema")
        if isinstance(input_schema, dict):
            compact["input_schema"] = input_schema
    else:
        compact["summary"] = _compact_value(result, limit=500)
    return compact


def _compact_search_result(item: object) -> object:
    if not isinstance(item, dict):
        return _compact_value(item, limit=160)
    return {
        key: _shorten(str(item.get(key) or ""), 180)
        for key in ("title", "url", "snippet", "source", "query_node")
        if item.get(key) is not None
    }


def _add_tail(target: dict[str, Any], key: str, value: object, limit: int) -> None:
    if value is None:
        return
    text = str(value)
    if not text:
        return
    target[f"{key}_tail"] = _shorten(text[-limit:], limit)


def _compact_value(value: object, *, limit: int) -> object:
    if isinstance(value, dict):
        return {str(key): _compact_value(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_value(item, limit=limit) for item in value[:10]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _shorten(str(value), limit) if isinstance(value, str) else value
    return _shorten(str(value), limit)


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


