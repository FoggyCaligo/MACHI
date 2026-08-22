from __future__ import annotations

from typing import Any

from .tool_runtime import ToolDefinition


_TOOL_SUMMARY_LIMIT = 160
_FIELD_DESCRIPTION_LIMIT = 96


def compact_tool_catalog(tool_definitions: list[ToolDefinition]) -> list[dict[str, object]]:
    """Return a self-sufficient compact contract for one normal tool call.

    The catalog intentionally exposes the information needed to choose and invoke a
    tool without first opening tool_manual. Long operational notes, recovery guidance,
    and full JSON Schema details remain available through tool_manual.
    """
    return [_compact_tool_definition(definition) for definition in tool_definitions]


def missing_required_arguments(arguments: dict[str, Any], definition: ToolDefinition) -> list[str]:
    schema = definition.input_schema if isinstance(definition.input_schema, dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    return [
        str(name)
        for name in required
        if str(name) not in arguments
        or arguments.get(str(name)) is None
        or arguments.get(str(name)) == ""
    ]


def _compact_tool_definition(definition: ToolDefinition) -> dict[str, object]:
    schema = definition.input_schema if isinstance(definition.input_schema, dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = {
        str(name)
        for name in (schema.get("required") if isinstance(schema.get("required"), list) else [])
    }

    fields: list[dict[str, object]] = []
    for name, raw_property in properties.items():
        property_schema = raw_property if isinstance(raw_property, dict) else {}
        field: dict[str, object] = {
            "name": str(name),
            "type": _compact_schema_type(property_schema),
            "required": str(name) in required,
        }
        description = _compact_field_description(property_schema.get("description"))
        if description:
            field["description"] = description
        enum_values = property_schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            field["enum"] = enum_values[:12]
        fields.append(field)

    return {
        "name": definition.name,
        "summary": _compact_tool_summary(definition.description),
        "input": fields,
        "call_template": {
            "tool": definition.name,
            "arguments": {
                field["name"]: _type_placeholder(str(field["type"]))
                for field in fields
                if field["required"] is True
            },
        },
    }


def _compact_schema_type(schema: dict[str, Any]) -> str:
    value = schema.get("type")
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    if isinstance(value, str) and value:
        if value == "array":
            items = schema.get("items") if isinstance(schema.get("items"), dict) else {}
            item_type = items.get("type")
            if isinstance(item_type, str) and item_type:
                return f"array<{item_type}>"
        return value
    return "any"


def _type_placeholder(type_name: str) -> str:
    return f"<{type_name}>"


def _compact_tool_summary(description: str) -> str:
    one_line = " ".join(str(description or "").split())
    if len(one_line) <= _TOOL_SUMMARY_LIMIT:
        return one_line
    return one_line[: _TOOL_SUMMARY_LIMIT - 3] + "..."


def _compact_field_description(description: object) -> str:
    one_line = " ".join(str(description or "").split())
    if not one_line:
        return ""
    if len(one_line) <= _FIELD_DESCRIPTION_LIMIT:
        return one_line
    return one_line[: _FIELD_DESCRIPTION_LIMIT - 3] + "..."
