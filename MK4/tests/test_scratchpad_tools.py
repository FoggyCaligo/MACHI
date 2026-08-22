from __future__ import annotations

import pytest

from MK4.tools.scratchpad_tools import (
    ScratchpadToolSuite,
    reset_request_scratchpad,
    start_request_scratchpad,
)
from MK4.tools.tool_runtime import ToolCall


@pytest.mark.asyncio
async def test_scratchpad_crud_within_one_request() -> None:
    registry = ScratchpadToolSuite().build_registry()
    token = start_request_scratchpad()
    try:
        created = await registry.run(ToolCall(
            tool="scratchpad_create",
            arguments={"note_id": "target", "content": "MK4/app/pipeline.py"},
        ))
        assert created == {
            "ok": True,
            "note_id": "target",
            "content": "MK4/app/pipeline.py",
        }

        read = await registry.run(ToolCall(
            tool="scratchpad_read",
            arguments={"note_id": "target"},
        ))
        assert read["content"] == "MK4/app/pipeline.py"

        updated = await registry.run(ToolCall(
            tool="scratchpad_update",
            arguments={"note_id": "target", "content": "MK4/tools/scratchpad_tools.py"},
        ))
        assert updated["content"] == "MK4/tools/scratchpad_tools.py"

        all_notes = await registry.run(ToolCall(tool="scratchpad_read", arguments={}))
        assert all_notes["notes"] == {"target": "MK4/tools/scratchpad_tools.py"}

        deleted = await registry.run(ToolCall(
            tool="scratchpad_delete",
            arguments={"note_id": "target"},
        ))
        assert deleted == {"ok": True, "note_id": "target"}
        assert (await registry.run(ToolCall(tool="scratchpad_read", arguments={}))) ["notes"] == {}
    finally:
        reset_request_scratchpad(token)


@pytest.mark.asyncio
async def test_scratchpad_create_update_delete_contract_failures_are_visible() -> None:
    registry = ScratchpadToolSuite().build_registry()
    token = start_request_scratchpad()
    try:
        await registry.run(ToolCall(
            tool="scratchpad_create",
            arguments={"note_id": "fact", "content": "first"},
        ))

        duplicate = await registry.run(ToolCall(
            tool="scratchpad_create",
            arguments={"note_id": "fact", "content": "second"},
        ))
        assert duplicate == {
            "ok": False,
            "error": "scratchpad_note_exists",
            "note_id": "fact",
        }

        missing_update = await registry.run(ToolCall(
            tool="scratchpad_update",
            arguments={"note_id": "missing", "content": "value"},
        ))
        assert missing_update["error"] == "scratchpad_note_not_found"

        missing_delete = await registry.run(ToolCall(
            tool="scratchpad_delete",
            arguments={"note_id": "missing"},
        ))
        assert missing_delete["error"] == "scratchpad_note_not_found"
    finally:
        reset_request_scratchpad(token)


@pytest.mark.asyncio
async def test_scratchpad_is_discarded_between_requests() -> None:
    registry = ScratchpadToolSuite().build_registry()

    first = start_request_scratchpad()
    try:
        await registry.run(ToolCall(
            tool="scratchpad_create",
            arguments={"note_id": "temporary", "content": "only this request"},
        ))
    finally:
        reset_request_scratchpad(first)

    second = start_request_scratchpad()
    try:
        read = await registry.run(ToolCall(tool="scratchpad_read", arguments={}))
        assert read == {"ok": True, "notes": {}}
    finally:
        reset_request_scratchpad(second)


@pytest.mark.asyncio
async def test_scratchpad_fails_when_no_request_scope_is_active() -> None:
    registry = ScratchpadToolSuite().build_registry()

    result = await registry.run(ToolCall(tool="scratchpad_read", arguments={}))

    assert result == {"ok": False, "error": "scratchpad_not_active"}
