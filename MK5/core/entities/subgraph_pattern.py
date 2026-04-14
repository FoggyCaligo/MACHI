from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SubgraphPattern:
    """Represents a stable, recurring structural pattern in the cognitive world graph.
    
    A pattern is a collection of nodes and edges that frequently co-occur and
    maintain consistent relationships. Patterns are more stable than individual
    edges: they persist across multiple thought cycles, accumulate evidence,
    and compete with alternative patterns when contradictions arise.
    """

    id: int | None = None
    pattern_uid: str = ""
    pattern_type: str = "untyped"  # chain, triangle, star, loop, shared_root, etc
    node_ids: list[int] = field(default_factory=list)
    edge_ids: list[int] = field(default_factory=list)
    
    # Structural metadata
    topology_hash: str = ""  # Canonical hash of the pattern's shape
    cardinality: int = 0  # Total number of nodes in this pattern
    edge_count: int = 0
    
    # Trust and stability: Pattern-level, separate from individual edges
    pattern_trust: float = 0.5  # Confidence in this pattern as stable
    backing_evidence_count: int = 0  # How many times has this pattern been confirmed
    conflict_count: int = 0  # How many times has input contradicted this pattern
    conflict_pressure: float = 0.0  # Accumulated contradiction pressure
    
    # Activation and revision
    is_active: bool = True
    revision_candidate_flag: bool = False
    superseded_by: str | None = None  # If this pattern lost, which pattern replaced it
    
    # Metadata
    payload: dict[str, Any] = field(default_factory=dict)
    created_from_event_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class PatternMatch:
    """Result of detecting a pattern during activation.
    
    When ThoughtView is built, PatternDetector finds which patterns from the
    durable world graph are activated by the current input.
    """

    pattern_id: int
    pattern: SubgraphPattern
    match_score: float  # 0.0-1.0: how well does input align with this pattern
    matched_node_ids: list[int]  # Which nodes from this query matched the pattern
    matched_edge_ids: list[int]  # Which edges from this query matched the pattern
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PatternConflictRecord:
    """Recorded when a contradiction signal involves a pattern, not just an edge.
    
    Different from ContradictionSignal (which targets individual edges):
    this tracks when a pattern itself is challenged as a whole structure.
    """

    pattern_id: int
    severity: str  # mild, medium, severe
    reason: str  # description of why pattern was in conflict
    inferred_alternative: int | None  # ID of a better-fitting alternative pattern
    score: float  # numeric severity
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PatternRevisionAction:
    """Action taken on a pattern as a result of thinking/conflict detection."""

    pattern_id: int
    action: str  # keep, demote, supersede, deactivate
    reason: str
    before_trust: float
    after_trust: float
    before_pressure: float
    after_pressure: float
    replaced_by: int | None = None  # If superseded, which pattern replaced it
    deactivated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
