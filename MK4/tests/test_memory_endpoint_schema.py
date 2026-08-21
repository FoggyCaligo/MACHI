from __future__ import annotations

from MK4.tools.memory_context import (
    register_created_node_ids,
    register_recalled_node_ids,
    reset_memory_turn_scope,
    set_memory_draft_answer,
    set_memory_turn_scope,
)
from MK4.tools.tool_runtime import ToolDefinition
from MK4.tools.turn_cycle import _with_current_scope_schemas


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, input_schema={"type": "object"})


def _variant_with_property(schema: dict, property_name: str) -> dict:
    for variant in schema.get("oneOf", []):
        if property_name in variant.get("properties", {}):
            return variant
    raise AssertionError(f"variant with {property_name!r} not found")


def test_write_memory_schema_separates_scoped_node_ids_from_writable_term_ids() -> None:
    token = set_memory_turn_scope("alpha beta")
    try:
        set_memory_draft_answer("gamma")
        register_recalled_node_ids({"node::recalled"})
        register_created_node_ids({"node::created"})
        definition = _with_current_scope_schemas([_definition("write_memory")])[0]
        endpoint = definition.input_schema["properties"]["object"]

        node_variant = _variant_with_property(endpoint, "node_id")
        term_variant = _variant_with_property(endpoint, "term_id")
        node_ids = node_variant["properties"]["node_id"]["enum"]
        term_ids = term_variant["properties"]["term_id"]["enum"]

        assert node_ids == ["node::created", "node::recalled"]
        assert "user:0:0" in term_ids
        assert "user:0:1" in term_ids
        assert "assistant:0:0" in term_ids
        assert not set(node_ids).intersection(term_ids)
    finally:
        reset_memory_turn_scope(token)


def test_revise_connect_schema_accepts_only_current_scope_node_ids() -> None:
    token = set_memory_turn_scope("alpha")
    try:
        set_memory_draft_answer("beta")
        register_recalled_node_ids({"node::a", "node::b"})
        definition = _with_current_scope_schemas([_definition("revise_memory")])[0]
        connect = next(
            variant
            for variant in definition.input_schema["oneOf"]
            if variant["properties"]["operation"]["enum"] == ["connect"]
        )
        subject = connect["properties"]["subject"]
        node_variant = _variant_with_property(subject, "node_id")

        assert node_variant["properties"]["node_id"]["enum"] == ["node::a", "node::b"]
        assert "term_id" not in node_variant["properties"]
    finally:
        reset_memory_turn_scope(token)
