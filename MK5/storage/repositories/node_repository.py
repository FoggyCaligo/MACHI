from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.node import Node
from storage.repositories.base import Repository


class NodeRepository(Repository, ABC):
    @abstractmethod
    def add(self, node: Node) -> Node:
        """Persist one node row and return the stored node."""

    @abstractmethod
    def get_by_id(self, node_id: int) -> Node | None:
        """Fetch one node by primary key."""

    @abstractmethod
    def get_by_uid(self, node_uid: str) -> Node | None:
        """Fetch one node by stable external uid."""

    @abstractmethod
    def get_by_address_hash(self, address_hash: str) -> Node | None:
        """Fetch one durable node by exact address hash."""

    @abstractmethod
    def list_by_address_hashes(self, address_hashes: Sequence[str]) -> Sequence[Node]:
        """Return nodes for each known address hash in input order."""

    @abstractmethod
    def list_by_ids(self, node_ids: Sequence[int]) -> Sequence[Node]:
        """Return nodes for the provided ids in input order."""

    @abstractmethod
    def search_by_normalized_value(
        self,
        normalized_value: str,
        *,
        active_only: bool = True,
        limit: int = 20,
    ) -> Sequence[Node]:
        """Search nodes by normalized value for exact lexical reuse."""

    @abstractmethod
    def update_payload(self, node_id: int, payload: dict) -> None:
        """Replace payload JSON for one node."""

    @abstractmethod
    def update_scores(
        self,
        node_id: int,
        *,
        trust_score: float | None = None,
        stability_score: float | None = None,
        revision_state: str | None = None,
    ) -> None:
        """Update quantitative node scores and revision state."""

    @abstractmethod
    def deactivate(self, node_id: int, *, revision_state: str = 'deprecated') -> None:
        """Deactivate one node while preserving its history row."""
