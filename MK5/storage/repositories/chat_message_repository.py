from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.chat_message import ChatMessage
from storage.repositories.base import Repository


class ChatMessageRepository(Repository, ABC):
    @abstractmethod
    def add(self, message: ChatMessage) -> ChatMessage:
        """Persist one raw chat message and return the stored row."""

    @abstractmethod
    def get_by_id(self, message_id: int) -> ChatMessage | None:
        """Fetch one message by internal primary key."""

    @abstractmethod
    def get_by_uid(self, message_uid: str) -> ChatMessage | None:
        """Fetch one message by stable external uid."""

    @abstractmethod
    def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 100,
        before_turn_index: int | None = None,
        after_turn_index: int | None = None,
    ) -> Sequence[ChatMessage]:
        """Return ordered chat messages for one session window."""

    @abstractmethod
    def list_by_ids(self, message_ids: Sequence[int]) -> Sequence[ChatMessage]:
        """Fetch multiple messages while preserving a stable order."""
