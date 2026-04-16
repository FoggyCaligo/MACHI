from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.edge import Edge
from storage.repositories.base import Repository


class EdgeRepository(Repository, ABC):
    @abstractmethod
    def add(self, edge: Edge) -> Edge:
        """Persist one relation row and return the stored edge."""

    @abstractmethod
    def get_by_id(self, edge_id: int) -> Edge | None:
        """Fetch one edge by primary key."""

    @abstractmethod
    def get_by_uid(self, edge_uid: str) -> Edge | None:
        """Fetch one edge by stable external uid."""

    @abstractmethod
    def find_active_relation(
        self,
        source_node_id: int,
        target_node_id: int,
        *,
        edge_family: str,
        connect_type: str
    ) -> Edge | None:
        """Return the currently active edge for the exact relation shape."""

    @abstractmethod
    def list_outgoing(
        self,
        source_node_id: int,
        *,
        edge_families: Sequence[str] | None = None,
        connect_types: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int | None = None,
    ) -> Sequence[Edge]:
        """Return outgoing edges for one source node."""

    @abstractmethod
    def list_incoming(
        self,
        target_node_id: int,
        *,
        edge_families: Sequence[str] | None = None,
        connect_types: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int | None = None,
    ) -> Sequence[Edge]:
        """Return incoming edges for one target node."""

    @abstractmethod
    def list_edges_for_nodes(
        self,
        node_ids: Sequence[int],
        *,
        active_only: bool = True,
    ) -> Sequence[Edge]:
        """Return all edges touching a local activation set."""

    @abstractmethod
    def bump_support(
        self,
        edge_id: int,
        *,
        delta: int = 1,
        trust_delta: float = 0.0,
    ) -> None:
        """Raise support_count and optionally adjust trust upward."""

    @abstractmethod
    def bump_conflict(
        self,
        edge_id: int,
        *,
        delta: int = 1,
        pressure_delta: float = 1.0,
        trust_delta: float = 0.0,
    ) -> None:
        """Raise conflict pressure and optionally lower trust."""

    @abstractmethod
    def set_revision_candidate(self, edge_id: int, *, flag: bool) -> None:
        """Mark or unmark an edge for structure revision review."""

    @abstractmethod
    def update_relation_detail(self, edge_id: int, relation_detail: dict) -> None:
        """Replace relation detail JSON after reasoning/refinement."""

    @abstractmethod
    def update_scores(
        self,
        edge_id: int,
        *,
        edge_weight: float | None = None,
        trust_score: float | None = None,
        contradiction_pressure: float | None = None,
    ) -> None:
        """Update edge-level quantitative signals."""

    @abstractmethod
    def update_counters(
        self,
        edge_id: int,
        *,
        support_count: int | None = None,
        conflict_count: int | None = None,
    ) -> None:
        """Set edge counters directly when consolidating duplicate relations."""

    @abstractmethod
    def reassign(
        self,
        edge_id: int,
        *,
        source_node_id: int | None = None,
        target_node_id: int | None = None,
    ) -> None:
        """Rewrite one or both endpoints without recreating the edge row."""

    @abstractmethod
    def list_revision_candidates(
        self,
        *,
        min_contradiction_pressure: float = 0.0,
        limit: int = 100,
    ) -> Sequence[Edge]:
        """Return edges that are ready for structure revision review."""

    @abstractmethod
    def deactivate(self, edge_id: int) -> None:
        """Deactivate one edge while preserving its history row."""

    @abstractmethod
    def update_connect_type(
        self,
        edge_id: int,
        *,
        connect_type: str,
        relation_detail: dict | None = None,
    ) -> None:
        """Update connect_type and optionally relation detail."""

    @abstractmethod
    def list_active_with_proposed_connect_type(
        self,
        *,
        limit: int = 500,
    ) -> Sequence[Edge]:
        """Return active edges that carry proposed_connect_type in relation_detail."""
