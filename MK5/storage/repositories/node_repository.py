from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.node import Node
from storage.repositories.base import Repository


class NodeRepository(Repository, ABC):
    @abstractmethod
    def add(self, node: Node) -> Node:
        """Persist one node and return the stored row."""

    @abstractmethod
    def get_by_id(self, node_id: int) -> Node | None:
        """Fetch one node by primary key."""

    @abstractmethod
    def get_by_uid(self, node_uid: str) -> Node | None:
        """Fetch one node by stable external uid."""

    @abstractmethod
    def get_by_address_hash(self, address_hash: str) -> Node | None:
        """Direct-address lookup for already-known meaning blocks."""

    @abstractmethod
    def list_by_address_hashes(self, address_hashes: Sequence[str]) -> Sequence[Node]:
        """Batch direct-address lookup for segmented input blocks."""

    @abstractmethod
    def list_by_ids(self, node_ids: Sequence[int]) -> Sequence[Node]:
        """Fetch multiple nodes in one repository call."""

    @abstractmethod
    def search_by_normalized_value(
        self,
        normalized_value: str,
        *,
        node_kinds: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int = 20,
    ) -> Sequence[Node]:
        """Fallback lookup when direct hash access alone is insufficient."""

    @abstractmethod
    def update_payload(self, node_id: int, payload: dict) -> None:
        """Replace the node payload JSON with a normalized payload."""

    @abstractmethod
    def update_scores(
        self,
        node_id: int,
        *,
        trust_score: float | None = None,
        stability_score: float | None = None,
        revision_state: str | None = None,
    ) -> None:
        """Update node-level trust/stability/revision signals."""

    @abstractmethod
    def deactivate(self, node_id: int, *, revision_state: str = "deprecated") -> None:
        """Mark the node inactive without deleting history."""
