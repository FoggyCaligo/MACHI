from __future__ import annotations

from pathlib import Path

import pytest

from MK5.tools.terminal_tools import TerminalToolSuite
from MK5.tools.tool_runtime import ToolCall
from MK5.tools.workspace_tools import WorkspaceFileToolSuite


@pytest.mark.asyncio
async def test_workspace_file_tool_can_write_and_read(tmp_path: Path) -> None:
    suite = WorkspaceFileToolSuite(tmp_path)
    registry = suite.build_registry()

    await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "write",
        "path": "notes/test.txt",
        "content": "hello",
    }))
    result = await registry.run(ToolCall(tool="workspace_file", arguments={
        "action": "read",
        "path": "notes/test.txt",
    }))

    assert result["content"] == "hello"


@pytest.mark.asyncio
async def test_terminal_tool_blocks_destructive_command(tmp_path: Path) -> None:
    suite = TerminalToolSuite(tmp_path)
    registry = suite.build_registry()

    with pytest.raises(ValueError):
        await registry.run(ToolCall(tool="terminal_command", arguments={"command": "rm -rf ."}))

