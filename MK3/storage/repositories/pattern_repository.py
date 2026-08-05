from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.entities.subgraph_pattern import SubgraphPattern
from storage.repositories.base import Repository


class PatternRepository(Repository, ABC):
    """Abstract interface for persistent storage of SubgraphPatterns.
    
    Patterns are larger structural units than individual edges. They accumulate
    evidence, track conflicts, and can supersede each other in revision scenarios.
    """

    @abstractmethod
    def add(self, pattern: SubgraphPattern) -> SubgraphPattern:
        """Persist one pattern and return the stored row with assigned id."""

    @abstractmethod
    def get_by_id(self, pattern_id: int) -> SubgraphPattern | None:
        """Fetch one pattern by primary key."""

    @abstractmethod
    def get_by_uid(self, pattern_uid: str) -> SubgraphPattern | None:
        """Fetch one pattern by stable external uid."""

    @abstractmethod
    def get_by_topology_hash(self, topology_hash: str) -> SubgraphPattern | None:
        """Look up pattern by its structural hash.
        
        Useful for deduplicating identical shapes discovered independently.
        """

    @abstractmethod
    def list_by_node_ids(
        self,
        node_ids: Sequence[int],
        *,
        active_only: bool = True,
    ) -> Sequence[SubgraphPattern]:
        """Return all patterns that contain any of the given nodes.
        
        Used during activation to find relevant patterns.
        """

    @abstractmethod
    def list_active_patterns(
        self,
        *,
        pattern_types: Sequence[str] | None = None,
        min_trust: float = 0.0,
        limit: int | None = None,
    ) -> Sequence[SubgraphPattern]:
        """Return active patterns, optionally filtered by type and trust."""

    @abstractmethod
    def update_payload(self, pattern_id: int, payload: dict) -> None:
        """Replace the pattern payload with updated metadata."""

    @abstractmethod
    def update_trust_and_pressure(
        self,
        pattern_id: int,
        *,
        pattern_trust: float | None = None,
        conflict_pressure: float | None = None,
        backing_evidence_count: int | None = None,
        conflict_count: int | None = None,
    ) -> None:
        """Update pattern-level trust, pressure, and evidence counts."""

    @abstractmethod
    def bump_backing_evidence(
        self,
        pattern_id: int,
        *,
        delta: int = 1,
        trust_delta: float = 0.0,
    ) -> None:
        """Increase backing_evidence_count and optionally raise trust."""

    @abstractmethod
    def bump_conflict(
        self,
        pattern_id: int,
        *,
        delta: int = 1,
        pressure_delta: float = 1.0,
        trust_delta: float = 0.0,
    ) -> None:
        """Increase conflict counts and adjust trust/pressure."""

    @abstractmethod
    def set_superseded(self, pattern_id: int, *, superseded_by: str) -> None:
        """Mark this pattern as superseded by another pattern (uid)."""

    @abstractmethod
    def deactivate(self, pattern_id: int) -> None:
        """Deactivate one pattern while preserving its history row."""
