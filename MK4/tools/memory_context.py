from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from ..core.graph.text_graph import tokenize_spans


@dataclass
class MemoryTurnScope:
    user_text: str
    assistant_text: str = ""
    recalled_node_ids: set[str] = field(default_factory=set)
    created_node_ids: set[str] = field(default_factory=set)
    mutation_enabled: bool = False


_memory_user_id: ContextVar[str] = ContextVar("memory_user_id", default="")
_memory_turn_scope: ContextVar[MemoryTurnScope | None] = ContextVar("memory_turn_scope", default=None)
_memory_commit_active: ContextVar[bool] = ContextVar("memory_commit_active", default=False)


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


def set_memory_turn_scope(user_text: str) -> Token[MemoryTurnScope | None]:
    return _memory_turn_scope.set(MemoryTurnScope(user_text=str(user_text)))


def reset_memory_turn_scope(token: Token[MemoryTurnScope | None]) -> None:
    _memory_turn_scope.reset(token)


def has_memory_turn_scope() -> bool:
    return _memory_turn_scope.get() is not None


def get_memory_turn_scope() -> MemoryTurnScope:
    scope = _memory_turn_scope.get()
    if scope is None:
        raise RuntimeError("memory turn scope is not set")
    return scope


def register_recalled_node_ids(node_ids: set[str] | list[str]) -> None:
    scope = get_memory_turn_scope()
    scope.recalled_node_ids.update(str(node_id) for node_id in node_ids if str(node_id).strip())


def register_created_node_ids(node_ids: set[str] | list[str]) -> None:
    scope = get_memory_turn_scope()
    scope.created_node_ids.update(str(node_id) for node_id in node_ids if str(node_id).strip())


def require_scoped_node_id(node_id: str) -> str:
    cleaned = str(node_id or "").strip()
    if not cleaned:
        raise ValueError("node_id must not be empty")
    scope = get_memory_turn_scope()
    if cleaned not in scope.recalled_node_ids and cleaned not in scope.created_node_ids:
        raise ValueError(f"node is outside the current turn graph scope: {cleaned}")
    return cleaned


def set_memory_draft_answer(answer: str) -> None:
    scope = get_memory_turn_scope()
    scope.assistant_text = str(answer)
    scope.mutation_enabled = True


def require_memory_mutation_enabled() -> None:
    if not get_memory_turn_scope().mutation_enabled:
        raise RuntimeError("memory mutation is only allowed after the final answer draft is fixed")


def get_writable_terms() -> list[dict[str, str]]:
    scope = get_memory_turn_scope()
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for source, text in (("user", scope.user_text), ("assistant", scope.assistant_text)):
        for span in tokenize_spans(text):
            normalized = span.normalized
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            items.append({
                "term_id": f"{source}:{span.sentence_index}:{span.token_index}",
                "source": source,
                "text": span.token,
            })
    return items


def resolve_writable_term(term_id: str) -> str:
    cleaned = str(term_id or "").strip()
    if not cleaned:
        raise ValueError("term_id must not be empty")
    for item in get_writable_terms():
        if item["term_id"] == cleaned:
            return item["text"]
    raise ValueError(f"term_id is not writable in the current turn: {cleaned}")


def set_memory_commit_active(active: bool) -> Token[bool]:
    return _memory_commit_active.set(bool(active))


def reset_memory_commit_active(token: Token[bool]) -> None:
    _memory_commit_active.reset(token)


def is_memory_commit_active() -> bool:
    return _memory_commit_active.get()
