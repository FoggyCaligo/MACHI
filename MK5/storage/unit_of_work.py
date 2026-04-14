from __future__ import annotations

from abc import ABC, abstractmethod

from storage.repositories.chat_message_repository import ChatMessageRepository
from storage.repositories.edge_repository import EdgeRepository
from storage.repositories.graph_event_repository import GraphEventRepository
from storage.repositories.node_pointer_repository import NodePointerRepository
from storage.repositories.node_repository import NodeRepository


class UnitOfWork(ABC):
    chat_messages: ChatMessageRepository
    nodes: NodeRepository
    edges: EdgeRepository
    graph_events: GraphEventRepository
    node_pointers: NodePointerRepository

    @abstractmethod
    def __enter__(self) -> "UnitOfWork":
        raise NotImplementedError

    @abstractmethod
    def __exit__(self, exc_type, exc, tb) -> None:
        raise NotImplementedError

    @abstractmethod
    def commit(self) -> None:
        """Persist the current transaction."""

    @abstractmethod
    def rollback(self) -> None:
        """Rollback the current transaction."""
