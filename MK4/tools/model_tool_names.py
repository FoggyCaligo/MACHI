from __future__ import annotations

from copy import deepcopy
from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolCall, ToolDefinition


_MODEL_NAME_SCHEMA_KEY = "x-model-name"
_TOOL_NAME_FIELDS = {"tool", "unknown_tool"}
_TOOL_NAME_LIST_FIELDS = {"available_tools", "missing_tools", "next_tools", "completion_tools"}


class ModelToolNameAdapter:
    """Expose model-friendly tool names while preserving runtime tool contracts."""

    def __init__(self, inner: ChatModel) -> None:
        self._inner = inner

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
        runtime_to_model, model_to_runtime = _tool_name_maps(tool_definitions)
        model_definitions = [
            _model_definition(definition, runtime_to_model[definition.name])
            for definition in tool_definitions
        ]
        model_history = [
            _map_tool_name_fields(event, runtime_to_model)
            for event in tool_history
        ]
        turn = await self._inner.next_turn(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=model_definitions,
            tool_history=model_history,
        )
        return _runtime_turn(turn, model_to_runtime)


def _tool_name_maps(
    tool_definitions: list[ToolDefinition],
) -> tuple[dict[str, str], dict[str, str]]:
    runtime_to_model: dict[str, str] = {}
    model_to_runtime: dict[str, str] = {}
    for definition in tool_definitions:
        model_name = _model_name(definition)
        if model_name in model_to_runtime and model_to_runtime[model_name] != definition.name:
            raise ValueError(f"Duplicate model-facing tool name: {model_name}")
        runtime_to_model[definition.name] = model_name
        model_to_runtime[model_name] = definition.name
    return runtime_to_model, model_to_runtime


def _model_name(definition: ToolDefinition) -> str:
    schema = definition.input_schema if isinstance(definition.input_schema, dict) else {}
    value = schema.get(_MODEL_NAME_SCHEMA_KEY)
    if value is None:
        return definition.name
    model_name = str(value).strip()
    if not model_name:
        raise ValueError(f"{_MODEL_NAME_SCHEMA_KEY} must be a non-empty string for {definition.name}")
    return model_name


def _model_definition(definition: ToolDefinition, model_name: str) -> ToolDefinition:
    schema = deepcopy(definition.input_schema)
    if isinstance(schema, dict):
        schema.pop(_MODEL_NAME_SCHEMA_KEY, None)
    return ToolDefinition(
        name=model_name,
        description=definition.description,
        input_schema=schema,
        model_visible=definition.model_visible,
    )


def _runtime_turn(turn: ModelTurn, model_to_runtime: dict[str, str]) -> ModelTurn:
    tool_calls = [
        ToolCall(
            tool=model_to_runtime.get(call.tool, call.tool),
            arguments=_runtime_arguments(call, model_to_runtime),
        )
        for call in turn.tool_calls
    ]
    return ModelTurn(
        final_answer=turn.final_answer,
        tool_calls=tool_calls,
        final_answer_kind=turn.final_answer_kind,
        completion_tools=[model_to_runtime.get(name, name) for name in turn.completion_tools],
    )


def _runtime_arguments(call: ToolCall, model_to_runtime: dict[str, str]) -> dict[str, Any]:
    arguments = deepcopy(call.arguments)
    if call.tool == "tool_manual" and isinstance(arguments.get("tool"), str):
        arguments["tool"] = model_to_runtime.get(arguments["tool"], arguments["tool"])
    return arguments


def _map_tool_name_fields(value: Any, mapping: dict[str, str], *, key: str | None = None) -> Any:
    if key in _TOOL_NAME_FIELDS and isinstance(value, str):
        return mapping.get(value, value)
    if key in _TOOL_NAME_LIST_FIELDS and isinstance(value, list):
        return [mapping.get(item, item) if isinstance(item, str) else item for item in value]
    if isinstance(value, dict):
        return {
            item_key: _map_tool_name_fields(item, mapping, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_map_tool_name_fields(item, mapping) for item in value]
    return deepcopy(value)
