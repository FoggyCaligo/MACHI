from __future__ import annotations

import asyncio
import locale
import os
import re
from pathlib import Path

from .. import config
from .tool_runtime import ToolDefinition, ToolRegistry


_WINDOWS_UNIX_COMMAND_RE = re.compile(
    r"(?:^|&&|\|\||[|&;])\s*(?:ls|cat|grep|pwd|rm|cp|mv|touch|which|head|tail)\b",
    re.IGNORECASE,
)
_WINDOWS_UNIX_FIND_RE = re.compile(
    r"(?:^|&&|\|\||[|&;])\s*find\s+[^\r\n]*(?:\s-name\b|\s-type\b|\s-maxdepth\b|\s-mindepth\b)",
    re.IGNORECASE,
)
_WINDOWS_UNIX_TREE_RE = re.compile(
    r"(?:^|&&|\|\||[|&;])\s*tree\s+[^\r\n]*\s-L(?:\s|$)",
    re.IGNORECASE,
)
_DIRECTORY_DISCOVERY_COMMAND_RE = re.compile(
    r"(?:^|&&|\|\||[|&;])\s*(?:ls|pwd|find|tree)\b",
    re.IGNORECASE,
)


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
                    "Run a shell command from the workspace root and return stdout/stderr. "
                    "Use this for shell work that file tools cannot do directly. This project runs on Windows cmd.exe. "
                    "For directory/project discovery, prefer file_tree instead of terminal commands. "
                    "Do not use direct Unix commands such as ls, cat, grep, pwd, rm, cp, mv, touch, head, or tail. "
                    "Use Windows commands such as dir/tree /F, or invoke PowerShell explicitly when shell work is needed. "
                    "For Windows user-profile or shell integration work, resolve known folders through Windows or PowerShell APIs "
                    "instead of guessing paths. For a requested current-user Startup registration, resolve the Startup folder "
                    "with [Environment]::GetFolderPath('Startup'), create a .lnk with the WScript.Shell CreateShortcut API, set "
                    "TargetPath to the already-discovered executable and WorkingDirectory to its parent directory, save it, then "
                    "re-open or inspect the shortcut to verify its TargetPath before claiming completion. "
                    "After a mutating terminal command, run a separate read/check command with verification=true. A verification "
                    "call must inspect resulting state and must not intentionally mutate it."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
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
        verification = arguments.get("verification") is True
        if not command:
            raise ValueError("terminal_command requires command")

        unsupported = self._unsupported_windows_command_result(command, verification=verification)
        if unsupported is not None:
            return unsupported

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
            "verification": verification,
            "filesystem_changed": bool(changed_paths),
            "changed_paths": changed_paths[:50],
            "changed_paths_truncated": len(changed_paths) > 50,
        }

    def _unsupported_windows_command_result(self, command: str, *, verification: bool) -> dict | None:
        if not _is_windows():
            return None
        if not (
            _WINDOWS_UNIX_COMMAND_RE.search(command)
            or _WINDOWS_UNIX_FIND_RE.search(command)
            or _WINDOWS_UNIX_TREE_RE.search(command)
        ):
            return None

        directory_discovery = bool(_DIRECTORY_DISCOVERY_COMMAND_RE.search(command))
        message = (
            "This terminal uses Windows cmd.exe, so the requested direct Unix shell command is not supported. "
            "Do not retry the same command. "
        )
        if directory_discovery:
            message += (
                "For directory or project inspection, use file_tree first. "
                "If a shell command is genuinely needed, use dir/tree /F or invoke PowerShell explicitly."
            )
            next_tools = ["file_tree", "terminal_command"]
        else:
            message += "Use the Windows equivalent or invoke PowerShell explicitly."
            next_tools = ["terminal_command"]

        return {
            "ok": False,
            "error": "unsupported_windows_shell_command",
            "message": message,
            "command": command,
            "cwd": str(self._workspace_root),
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "verification": verification,
            "filesystem_changed": False,
            "changed_paths": [],
            "changed_paths_truncated": False,
            "recovery": {
                "next_tools": next_tools,
                "prefer_file_tree": directory_discovery,
            },
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
        # mbcs follows the active Windows ANSI code page. cp949 is a final explicit
        # fallback for Korean Windows where cmd.exe commonly emits localized errors.
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
