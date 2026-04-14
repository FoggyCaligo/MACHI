from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.graph_event import GraphEvent
from storage.repositories.base import Repository


class GraphEventRepository(Repository, ABC):
    @abstractmethod
    def add(self, event: GraphEvent) -> GraphEvent:
        """Persist one graph event and return the stored row."""

    @abstractmethod
    def get_by_id(self, event_id: int) -> GraphEvent | None:
        """Fetch one graph event by primary key."""

    @abstractmethod
    def get_by_uid(self, event_uid: str) -> GraphEvent | None:
        """Fetch one graph event by stable external uid."""

    @abstractmethod
    def list_for_message(self, message_id: int) -> Sequence[GraphEvent]:
        """Return graph events caused by one chat message."""

    @abstractmethod
    def list_for_node(self, node_id: int, *, limit: int = 100) -> Sequence[GraphEvent]:
        """Return graph events related to one node."""

    @abstractmethod
    def list_for_edge(self, edge_id: int, *, limit: int = 100) -> Sequence[GraphEvent]:
        """Return graph events related to one edge."""

    @abstractmethod
    def list_recent(
        self,
        *,
        event_types: Sequence[str] | None = None,
        limit: int = 100,
    ) -> Sequence[GraphEvent]:
        """Return the latest graph events for debugging and replay."""
