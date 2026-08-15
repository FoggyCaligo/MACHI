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
                description="Read, list, write, or append files using paths resolved from the workspace root. Parent and absolute paths are allowed.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                    },
                    "required": ["action", "path"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    def _resolve(self, relative_path: str) -> Path:
        raw_path = Path(relative_path)
        return raw_path.resolve() if raw_path.is_absolute() else (self._workspace_root / raw_path).resolve()

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
            return {"ok": True, "path": relative_path, "status": "written", "bytes": len(content.encode("utf-8"))}
        if action == "append":
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
            return {"ok": True, "path": relative_path, "status": "appended", "bytes": len(content.encode("utf-8"))}
        if action == "replace":
            old = str(arguments.get("old") or "")
            new = str(arguments.get("new") or "")
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
            if old == "":
                raise ValueError("workspace_file replace requires old")
            original = target.read_text(encoding="utf-8")
            count = original.count(old)
            if count == 0:
                return {
                    "ok": False,
                    "path": relative_path,
                    "error": "old_not_found",
                    "message": "Old text not found.",
                }
            updated = original.replace(old, new)
            target.write_text(updated, encoding="utf-8")
            return {
                "ok": True,
                "path": relative_path,
                "status": "replaced",
                "replacements": count,
                "bytes": len(updated.encode("utf-8")),
            }
        raise ValueError("workspace_file action must be one of: read, list, write, append, replace")
