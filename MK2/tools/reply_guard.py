from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True)
class ReplyGuardContext:
    has_direct_source: bool
    has_project_scope: bool
    has_recent_source: bool
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_guard_context(context: dict | None = None) -> ReplyGuardContext:
    context = context or {}
    source_contents = context.get("source_contents") or context.get("attached_text") or []
    if isinstance(source_contents, str):
        source_count = 1 if source_contents.strip() else 0
    else:
        source_count = len(source_contents) if source_contents else 0

    recent_sources = context.get("recent_sources") or []
    return ReplyGuardContext(
        has_direct_source=bool(source_count or context.get("project_chunks")),
        has_project_scope=bool(context.get("project_chunks")),
        has_recent_source=bool(recent_sources),
        source_count=source_count,
    )
