from __future__ import annotations

from pathlib import Path

from .. import config
from .tool_runtime import ToolDefinition, ToolRegistry


class WorkspaceFileToolSuite:
    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = (workspace_root or config.WORKSPACE_ROOT).resolve()

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="workspace_file",
                description="Read, list, write, or append files under the workspace root.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["action", "path"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._workspace_root / relative_path).resolve()
        if self._workspace_root not in candidate.parents and candidate != self._workspace_root:
            raise ValueError("Path escapes workspace root.")
        return candidate

    async def _run(self, arguments: dict) -> dict:
        action = str(arguments.get("action") or "").strip().lower()
        relative_path = str(arguments.get("path") or "").strip()
        content = str(arguments.get("content") or "")
        if not relative_path:
            raise ValueError("workspace_file requires path")

        target = self._resolve(relative_path)
        if action == "read":
            if not target.exists():
                return {
                    "ok": False,
                    "path": relative_path,
                    "error": "not_found",
                    "message": f"File not found: {relative_path}",
                }
            if not target.is_file():
                return {
                    "ok": False,
                    "path": relative_path,
                    "error": "not_file",
                    "message": f"Path is not a file: {relative_path}",
                }
            return {"ok": True, "path": relative_path, "content": target.read_text(encoding="utf-8")}
        if action == "list":
            if not target.exists():
                return {
                    "ok": False,
                    "path": relative_path,
                    "error": "not_found",
                    "message": f"Path not found: {relative_path}",
                }
            if not target.is_dir():
                return {
                    "ok": False,
                    "path": relative_path,
                    "error": "not_directory",
                    "message": f"Path is not a directory: {relative_path}",
                }
            return {
                "ok": True,
                "path": relative_path,
                "entries": sorted(item.name for item in target.iterdir()),
            }
        if action == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"path": relative_path, "status": "written", "bytes": len(content.encode("utf-8"))}
        if action == "append":
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
            return {"path": relative_path, "status": "appended", "bytes": len(content.encode("utf-8"))}
        raise ValueError("workspace_file action must be one of: read, list, write, append")
