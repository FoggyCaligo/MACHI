from __future__ import annotations

import pytest

from MK4.tools.tool_runtime import (
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    get_file_working_root,
    reset_file_working_root,
    set_file_working_root,
)


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, input_schema={"type": "object"})


@pytest.mark.asyncio
async def test_first_top_level_discovery_adopts_working_root() -> None:
    registry = ToolRegistry()

    async def tree(arguments: dict) -> dict:
        return {"ok": True, "root": arguments.get("root")}

    registry.register(_definition("file_tree"), tree)
    token = set_file_working_root(".")
    try:
        result = await registry.run(ToolCall(tool="file_tree", arguments={"root": "MK4"}))
        assert get_file_working_root() == "MK4"
        assert result["file_working_root"] == "MK4"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_relative_paths_are_prefixed_after_root_is_set() -> None:
    registry = ToolRegistry()

    async def read(arguments: dict) -> dict:
        return {"ok": True, "path": arguments["path"]}

    registry.register(_definition("file_read"), read)
    token = set_file_working_root("MK4")
    try:
        call = ToolCall(tool="file_read", arguments={"path": "app/static/index.html"})
        result = await registry.run(call)
        assert call.arguments["path"] == "MK4/app/static/index.html"
        assert result["path"] == "MK4/app/static/index.html"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_dot_or_missing_search_root_uses_working_root_without_changing_it() -> None:
    registry = ToolRegistry()

    async def search(arguments: dict) -> dict:
        return {"ok": True, "root": arguments["root"]}

    registry.register(_definition("file_text_search"), search)
    token = set_file_working_root("MK4")
    try:
        call = ToolCall(tool="file_text_search", arguments={"query": "<select"})
        result = await registry.run(call)
        assert call.arguments["root"] == "MK4"
        assert result["root"] == "MK4"
        assert get_file_working_root() == "MK4"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_workspace_relative_path_is_not_double_prefixed() -> None:
    registry = ToolRegistry()

    async def read(arguments: dict) -> dict:
        return {"ok": True, "path": arguments["path"]}

    registry.register(_definition("file_read"), read)
    token = set_file_working_root("MK4")
    try:
        call = ToolCall(tool="file_read", arguments={"path": "MK4/app/static/index.html"})
        await registry.run(call)
        assert call.arguments["path"] == "MK4/app/static/index.html"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_file_tree_can_switch_from_mk4_to_mk5_via_parent_path() -> None:
    registry = ToolRegistry()

    async def tree(arguments: dict) -> dict:
        return {"ok": True, "root": arguments["root"]}

    registry.register(_definition("file_tree"), tree)
    token = set_file_working_root("MK4")
    try:
        call = ToolCall(tool="file_tree", arguments={"root": "../MK5"})
        result = await registry.run(call)
        assert call.arguments["root"] == "MK5"
        assert result["file_working_root"] == "MK5"
        assert get_file_working_root() == "MK5"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_parent_traversal_can_leave_initial_workspace() -> None:
    registry = ToolRegistry()

    async def read(arguments: dict) -> dict:
        return {"ok": True, "path": arguments["path"]}

    registry.register(_definition("file_read"), read)
    token = set_file_working_root("MK4")
    try:
        call = ToolCall(tool="file_read", arguments={"path": "../../outside/config.txt"})
        await registry.run(call)
        assert call.arguments["path"] == "../outside/config.txt"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_absolute_path_bypasses_working_root() -> None:
    registry = ToolRegistry()

    async def read(arguments: dict) -> dict:
        return {"ok": True, "path": arguments["path"]}

    registry.register(_definition("file_read"), read)
    token = set_file_working_root("MK5")
    try:
        call = ToolCall(tool="file_read", arguments={"path": "C:/Users/example/other-repo/file.txt"})
        await registry.run(call)
        assert call.arguments["path"] == "C:/Users/example/other-repo/file.txt"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_file_tree_can_set_absolute_working_root() -> None:
    registry = ToolRegistry()

    async def tree(arguments: dict) -> dict:
        return {"ok": True, "root": arguments["root"]}

    registry.register(_definition("file_tree"), tree)
    token = set_file_working_root("MK4")
    try:
        call = ToolCall(tool="file_tree", arguments={"root": "C:/Users/example/other-repo"})
        result = await registry.run(call)
        assert call.arguments["root"] == "C:/Users/example/other-repo"
        assert result["file_working_root"] == "C:/Users/example/other-repo"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_document_and_image_tools_share_arbitrary_working_root() -> None:
    registry = ToolRegistry()

    async def echo(arguments: dict) -> dict:
        return {"ok": True, "path": arguments["path"]}

    registry.register(_definition("document_read"), echo)
    registry.register(_definition("image_analyze"), echo)
    token = set_file_working_root("MK5")
    try:
        document_call = ToolCall(tool="document_read", arguments={"path": "./docs/a.pdf"})
        image_call = ToolCall(tool="image_analyze", arguments={"path": "assets/a.png"})
        await registry.run(document_call)
        await registry.run(image_call)
        assert document_call.arguments["path"] == "MK5/docs/a.pdf"
        assert image_call.arguments["path"] == "MK5/assets/a.png"
    finally:
        reset_file_working_root(token)


@pytest.mark.asyncio
async def test_uploaded_workspace_path_bypasses_project_root() -> None:
    registry = ToolRegistry()

    async def read(arguments: dict) -> dict:
        return {"ok": True, "path": arguments["path"]}

    registry.register(_definition("file_read"), read)
    token = set_file_working_root("MK5")
    try:
        call = ToolCall(tool="file_read", arguments={"path": ".mk4_uploads/upload.txt"})
        await registry.run(call)
        assert call.arguments["path"] == ".mk4_uploads/upload.txt"
    finally:
        reset_file_working_root(token)
