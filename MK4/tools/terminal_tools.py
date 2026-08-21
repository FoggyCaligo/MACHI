from __future__ import annotations

import asyncio
import locale
import os
from pathlib import Path

from .. import config
from .tool_runtime import ToolDefinition, ToolRegistry


def _is_windows() -> bool:
    return os.name == "nt"


class TerminalToolSuite:
    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = (workspace_root or config.WORKSPACE_ROOT).resolve()

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="terminal_command",
                description=(
                    "Run a shell command from the workspace root and return stdout/stderr. This project launches Windows "
                    "cmd.exe; invoke PowerShell explicitly when PowerShell features are useful. The command may inspect or "
                    "modify files, user-profile locations, registry, shell configuration, Startup registration, and other "
                    "system state when the task requires it. Do not claim that a command is unavailable or unauthorized unless "
                    "the actual shell/tool execution reports that failure. Set changes_state=true when a command intentionally "
                    "changes persistent state. After a state-changing command, run a separate read/check command with "
                    "verification=true. A verification call must inspect resulting state and must not intentionally mutate it."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "changes_state": {
                            "type": "boolean",
                            "description": (
                                "Set true when this command intentionally changes filesystem, registry, shell configuration, "
                                "startup registration, or other persistent system state."
                            ),
                        },
                        "verification": {
                            "type": "boolean",
                            "description": (
                                "Set true only for a follow-up read/check command that verifies a prior terminal change. "
                                "The command must not intentionally mutate state."
                            ),
                        },
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
        changes_state = arguments.get("changes_state") is True
        verification = arguments.get("verification") is True
        if not command:
            raise ValueError("terminal_command requires command")
        if changes_state and verification:
            raise ValueError("terminal_command cannot set both changes_state=true and verification=true")

        before = self._snapshot_files()
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

        after = self._snapshot_files()
        changed_paths = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
        return {
            "ok": process.returncode == 0,
            "command": command,
            "cwd": str(self._workspace_root),
            "returncode": process.returncode,
            "stdout": _decode_process_output(stdout),
            "stderr": _decode_process_output(stderr),
            "changes_state": changes_state,
            "verification": verification,
            "filesystem_changed": bool(changed_paths),
            "changed_paths": changed_paths[:50],
            "changed_paths_truncated": len(changed_paths) > 50,
        }

    def _snapshot_files(self) -> dict[str, tuple[int, int]]:
        snapshot_root = self._workspace_root.parent
        ignored_dirs = {".git", ".uv-cache", ".uv-python", "__pycache__", "node_modules", ".pytest_cache"}
        snapshot: dict[str, tuple[int, int]] = {}
        for path in snapshot_root.rglob("*"):
            if any(part in ignored_dirs for part in path.parts):
                continue
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            try:
                relative = str(path.relative_to(snapshot_root))
            except ValueError:
                relative = str(path)
            snapshot[relative] = (stat.st_size, stat.st_mtime_ns)
        return snapshot


def _decode_process_output(data: bytes) -> str:
    """Decode subprocess output without corrupting localized Windows cmd.exe messages."""
    if not data:
        return ""

    encodings: list[str] = ["utf-8"]
    preferred = locale.getpreferredencoding(False)
    if preferred and preferred.lower().replace("-", "") != "utf8":
        encodings.append(preferred)
    if _is_windows():
        encodings.extend(["mbcs", "cp949"])

    seen: set[str] = set()
    for encoding in encodings:
        key = encoding.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    return data.decode("utf-8", errors="replace")
