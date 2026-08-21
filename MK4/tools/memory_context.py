from __future__ import annotations

from contextvars import ContextVar, Token


_memory_user_id: ContextVar[str] = ContextVar("memory_user_id", default="")


def set_memory_user_id(user_id: str) -> Token[str]:
    normalized = user_id.strip()
    if not normalized:
        raise ValueError("user_id must not be empty")
    return _memory_user_id.set(normalized)


def reset_memory_user_id(token: Token[str]) -> None:
    _memory_user_id.reset(token)


def get_memory_user_id() -> str:
    user_id = _memory_user_id.get().strip()
    if not user_id:
        raise RuntimeError("memory user context is not set")
    return user_id
