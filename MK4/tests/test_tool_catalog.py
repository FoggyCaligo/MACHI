from __future__ import annotations

import pytest

from MK4.tools.llm_client import ModelTurn
from MK4.tools.tool_catalog import ToolCatalogChatModel, _compact_tool_summary, _system_with_tool_catalog
from MK4.tools.tool_runtime import ToolDefinition


class _CapturingModel:
    def __init__(self) -> None:
        self.system = ""

    async def next_turn(self, **kwargs):
        self.system = kwargs["system"]
        return ModelTurn(final_answer="ok")


def test_system_tool_catalog_contains_name_and_compact_purpose_without_schema() -> None:
    definitions = [
        ToolDefinition(
            name="graph_search",
            description="Search persistent graph memory for relevant past information. Returns compact graph context.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
        ToolDefinition(
            name="file_read",
            description="Read a file from the current working root.\nUse it before editing a target file.",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    ]

    system = _system_with_tool_catalog("base", definitions)

    assert "- graph_search: Search persistent graph memory" in system
    assert "- file_read: Read a file from the current working root. Use it before editing a target file." in system
    assert "input_schema" not in system
    assert '"properties"' not in system
    assert "use tool_manual for full schema/details" in system


def test_tool_summary_is_one_line_and_capped() -> None:
    assert _compact_tool_summary("first\nsecond") == "first second"
    assert len(_compact_tool_summary("x" * 400)) <= 180


@pytest.mark.asyncio
async def test_catalog_wrapper_preserves_turn_and_arguments() -> None:
    delegate = _CapturingModel()
    model = ToolCatalogChatModel(delegate)
    definition = ToolDefinition(name="example", description="Example tool.", input_schema={})

    turn = await model.next_turn(
        system="base",
        user_message="hello",
        model=None,
        memory_summary=[],
        tool_definitions=[definition],
        tool_history=[],
    )

    assert turn.final_answer == "ok"
    assert "- example: Example tool." in delegate.system
