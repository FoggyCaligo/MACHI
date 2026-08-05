from __future__ import annotations

import asyncio
from pathlib import Path

from .. import config
from .tool_runtime import ToolDefinition, ToolRegistry


_BLOCKED_TERMINAL_TOKENS = (
    "del ",
    " rm ",
    "rm -",
    "rmdir ",
    "shutdown",
    "reboot",
    "format ",
    "mkfs",
    "diskpart",
)


class TerminalToolSuite:
    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = (workspace_root or config.WORKSPACE_ROOT).resolve()

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="terminal_command",
                description="Run a non-destructive shell command in the workspace root and return stdout/stderr.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    async def _run(self, arguments: dict) -> dict:
        command = str(arguments.get("command") or "").strip()
        if not command:
            raise ValueError("terminal_command requires command")

        lowered = f" {command.lower()} "
        if any(token in lowered for token in _BLOCKED_TERMINAL_TOKENS):
            raise ValueError("Blocked potentially destructive terminal command.")

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self._workspace_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=config.TERMINAL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise TimeoutError(f"terminal_command timed out after {config.TERMINAL_TIMEOUT_SECONDS:.0f}s")

        return {
            "command": command,
            "returncode": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
