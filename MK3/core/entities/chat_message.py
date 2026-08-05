from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChatMessage:
    id: int | None = None
    message_uid: str = ""
    session_id: str = ""
    turn_index: int = 0
    role: str = "user"
    content: str = ""
    content_hash: str | None = None
    attached_files: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
