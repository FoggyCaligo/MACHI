from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from core.entities.subgraph_pattern import PatternMatch


class ConflictResolutionStrategy(Enum):
    """Strategies for resolving conflicts between competing patterns."""
    HIGHEST_TRUST = "highest_trust"  # Keep pattern with highest trust score
    MOST_RECENT = "most_recent"      # Keep most recently activated pattern
    LEAST_DISRUPTIVE = "least_disruptive"  # Minimize impact on existing structure
    CONSENSUS = "consensus"          # Use voting/consensus among overlapping patterns


@dataclass(slots=True)
class ConflictResolutionPolicy:
    """Unified policy for resolving pattern conflicts.

    Used for both node-level conflicts (multiple patterns on same node)
    and graph-level conflicts (overlapping patterns across the graph).
    """

    strategy: ConflictResolutionStrategy
    trust_threshold: float = 0.5  # Minimum trust required to activate
    max_conflicts_per_node: int = 3  # Maximum patterns per node
    consensus_threshold: float = 0.7  # Required consensus ratio for CONSENSUS strategy

    def resolve_node_conflicts(self, competing_patterns: list[PatternMatch]) -> list[PatternMatch]:
        """Resolve conflicts when multiple patterns compete for the same node(s)."""
        return self._resolve_conflicts(competing_patterns, "node")

    def resolve_graph_conflicts(self, competing_patterns: list[PatternMatch]) -> list[PatternMatch]:
        """Resolve conflicts when patterns overlap across the graph."""
        return self._resolve_conflicts(competing_patterns, "graph")

    def _resolve_conflicts(self, competing_patterns: list[PatternMatch],
                          conflict_type: str) -> list[PatternMatch]:
        """Internal conflict resolution logic."""
        if not competing_patterns:
            return []

        if len(competing_patterns) == 1:
            return competing_patterns

        # Filter by trust threshold
        qualified_patterns = [
            p for p in competing_patterns
            if p.pattern.pattern_trust >= self.trust_threshold
        ]

        if not qualified_patterns:
            return []

        # Apply resolution strategy
        match self.strategy:
            case ConflictResolutionStrategy.HIGHEST_TRUST:
                return self._resolve_by_highest_trust(qualified_patterns)
            case ConflictResolutionStrategy.MOST_RECENT:
                return self._resolve_by_most_recent(qualified_patterns)
            case ConflictResolutionStrategy.LEAST_DISRUPTIVE:
                return self._resolve_by_least_disruptive(qualified_patterns, conflict_type)
            case ConflictResolutionStrategy.CONSENSUS:
                return self._resolve_by_consensus(qualified_patterns)
            case _:
                return qualified_patterns[:1]  # Default to first one

    def _resolve_by_highest_trust(self, patterns: list[PatternMatch]) -> list[PatternMatch]:
        """Keep pattern(s) with highest trust score."""
        if not patterns:
            return []

        max_trust = max(p.pattern.pattern_trust for p in patterns)
        return [p for p in patterns if p.pattern.pattern_trust == max_trust]

    def _resolve_by_most_recent(self, patterns: list[PatternMatch]) -> list[PatternMatch]:
        """Keep most recently activated pattern."""
        if not patterns:
            return []

        # Sort by activation time (assuming newer patterns have higher IDs or timestamps)
        # For now, use pattern ID as proxy for recency
        sorted_patterns = sorted(patterns, key=lambda p: p.pattern.id or 0, reverse=True)
        return [sorted_patterns[0]]

    def _resolve_by_least_disruptive(self, patterns: list[PatternMatch],
                                    conflict_type: str) -> list[PatternMatch]:
        """Keep pattern that minimally disrupts existing structure."""
        if not patterns:
            return []

        if conflict_type == "node":
            # For node conflicts, prefer patterns with fewer overlapping nodes
            return [min(patterns, key=lambda p: len(p.matched_node_ids))]
        else:
            # For graph conflicts, prefer patterns with fewer overlapping edges
            return [min(patterns, key=lambda p: len(p.matched_edge_ids))]

    def _resolve_by_consensus(self, patterns: list[PatternMatch]) -> list[PatternMatch]:
        """Use consensus voting among patterns."""
        if not patterns:
            return []

        # Simple consensus: patterns that appear in majority of matches
        # For now, just return all patterns if they meet consensus threshold
        total_patterns = len(patterns)
        if total_patterns == 0:
            return []

        # If all patterns agree on structure, keep them all
        # This is a simplified implementation
        consensus_patterns = []
        for pattern in patterns:
            # Calculate how many other patterns it agrees with
            agreement_count = sum(1 for other in patterns
                                if self._patterns_agree(pattern, other))
            agreement_ratio = agreement_count / total_patterns

            if agreement_ratio >= self.consensus_threshold:
                consensus_patterns.append(pattern)

        return consensus_patterns if consensus_patterns else patterns[:1]

    def _patterns_agree(self, pattern1: PatternMatch, pattern2: PatternMatch) -> bool:
        """Check if two patterns agree on their structure."""
        if pattern1 == pattern2:
            return True

        # Simple agreement: same topology type and similar trust levels
        return (pattern1.pattern.pattern_type == pattern2.pattern.pattern_type and
                abs(pattern1.pattern.pattern_trust - pattern2.pattern.pattern_trust) < 0.2)


# Default policy instance
DEFAULT_CONFLICT_POLICY = ConflictResolutionPolicy(
    strategy=ConflictResolutionStrategy.HIGHEST_TRUST,
    trust_threshold=0.5,
    max_conflicts_per_node=3,
    consensus_threshold=0.7
)