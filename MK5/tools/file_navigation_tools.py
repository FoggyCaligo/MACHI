from __future__ import annotations

from pathlib import Path

from .. import config
from .tool_runtime import ToolDefinition, ToolRegistry


_IGNORED_DIRS = {
    ".git",
    ".uv-cache",
    ".uv-python",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
}


class FileNavigationToolSuite:
    """Small, explicit discovery tools for local coding/file-editing workflows."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = (workspace_root or config.WORKSPACE_ROOT).resolve()

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="file_tree",
                description=(
                    "Inspect a directory tree before guessing file paths. Use this when you know the project or "
                    "folder but do not yet know which file to read. Returns workspace-relative directories and files. "
                    "After locating a likely file, continue with file_read instead of stopping."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "depth": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            ),
            self._tree,
        )
        registry.register(
            ToolDefinition(
                name="file_text_search",
                description=(
                    "Search text inside UTF-8 workspace files and return exact paths, line numbers, and matching lines. "
                    "Use this when you know text, a HTML label, CSS class, function name, symbol, or code fragment but "
                    "do not know which file contains it. Use file_search instead when searching by filename/glob. "
                    "After finding a likely file, continue with file_read and then file_update when editing is requested."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "root": {"type": "string"},
                        "pattern": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._text_search,
        )
        return registry

    def _resolve(self, relative_path: str) -> Path:
        raw_path = Path(relative_path)
        return raw_path.resolve() if raw_path.is_absolute() else (self._workspace_root / raw_path).resolve()

    def _display_path(self, path: Path) -> str:
        try:
            return path.relative_to(self._workspace_root).as_posix()
        except ValueError:
            return str(path)

    @staticmethod
    def _ignored(path: Path) -> bool:
        return any(part in _IGNORED_DIRS for part in path.parts)

    async def _tree(self, arguments: dict) -> dict:
        root_text = str(arguments.get("root") or ".").strip() or "."
        try:
            depth = max(1, min(int(arguments.get("depth", 3)), 8))
        except (TypeError, ValueError):
            depth = 3
        try:
            limit = max(1, min(int(arguments.get("limit", 120)), 400))
        except (TypeError, ValueError):
            limit = 120

        root = self._resolve(root_text)
        if not root.exists():
            return {
                "ok": False,
                "root": root_text,
                "error": "not_found",
                "message": f"Tree root not found: {root_text}",
                "entries": [],
            }
        if not root.is_dir():
            return {
                "ok": False,
                "root": root_text,
                "error": "not_directory",
                "message": f"Tree root is not a directory: {root_text}",
                "entries": [],
            }

        entries: list[dict[str, object]] = []
        truncated = False
        try:
            candidates = sorted(root.rglob("*"), key=lambda path: str(path).lower())
            for path in candidates:
                if self._ignored(path):
                    continue
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    continue
                if len(relative.parts) > depth:
                    continue
                entries.append({
                    "path": self._display_path(path),
                    "type": "directory" if path.is_dir() else "file",
                    "depth": len(relative.parts),
                })
                if len(entries) >= limit:
                    truncated = True
                    break
        except OSError as exc:
            return {
                "ok": False,
                "root": root_text,
                "error": "tree_failed",
                "message": str(exc),
                "entries": [],
            }

        return {
            "ok": True,
            "workspace_root": str(self._workspace_root),
            "root": root_text,
            "depth": depth,
            "entries": entries,
            "count": len(entries),
            "truncated": truncated,
        }

    async def _text_search(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "")
        if not query.strip():
            return {
                "ok": False,
                "error": "invalid_arguments",
                "message": "file_text_search requires a non-empty query.",
                "matches": [],
            }
        root_text = str(arguments.get("root") or ".").strip() or "."
        pattern = str(arguments.get("pattern") or "*").strip() or "*"
        try:
            limit = max(1, min(int(arguments.get("limit", 40)), 200))
        except (TypeError, ValueError):
            limit = 40

        root = self._resolve(root_text)
        if not root.exists():
            return {
                "ok": False,
                "root": root_text,
                "query": query,
                "error": "not_found",
                "message": f"Search root not found: {root_text}",
                "matches": [],
            }
        if not root.is_dir():
            return {
                "ok": False,
                "root": root_text,
                "query": query,
                "error": "not_directory",
                "message": f"Search root is not a directory: {root_text}",
                "matches": [],
            }

        matches: list[dict[str, object]] = []
        scanned_files = 0
        skipped_files = 0
        truncated = False
        query_folded = query.casefold()

        try:
            candidates = sorted(root.rglob(pattern), key=lambda path: str(path).lower())
        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "root": root_text,
                "query": query,
                "pattern": pattern,
                "error": "invalid_search",
                "message": str(exc),
                "matches": [],
            }

        for path in candidates:
            if not path.is_file() or self._ignored(path):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    skipped_files += 1
                    continue
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                skipped_files += 1
                continue
            scanned_files += 1
            for line_number, line in enumerate(content.splitlines(), start=1):
                if query_folded not in line.casefold():
                    continue
                matches.append({
                    "path": self._display_path(path),
                    "line": line_number,
                    "text": line.strip()[:500],
                })
                if len(matches) >= limit:
                    truncated = True
                    break
            if truncated:
                break

        return {
            "ok": True,
            "workspace_root": str(self._workspace_root),
            "root": root_text,
            "pattern": pattern,
            "query": query,
            "matches": matches,
            "count": len(matches),
            "scanned_files": scanned_files,
            "skipped_files": skipped_files,
            "truncated": truncated,
        }
