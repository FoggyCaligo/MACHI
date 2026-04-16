from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.subgraph_pattern import PatternMatch, SubgraphPattern
from core.entities.thought_view import ThoughtView
from core.policies.conflict_resolution_policy import ConflictResolutionPolicy, DEFAULT_CONFLICT_POLICY


@dataclass(slots=True)
class PatternDetector:
    """Detects activated patterns in a ThoughtView.
    
    Analyzes the local graph structure (nodes + edges) to identify
    recurring patterns that are relevant to the current thought process.
    """

    conflict_policy: ConflictResolutionPolicy = field(default_factory=lambda: DEFAULT_CONFLICT_POLICY)

    def detect_patterns(self, thought_view: ThoughtView) -> list[PatternMatch]:
        """Analyze ThoughtView and return activated patterns.
        
        For now, implements basic pattern detection:
        1. Group nodes by connectivity
        2. Identify basic topology types (chain, star, triangle, etc.)
        3. Create PatternMatch objects with match scores
        4. Resolve conflicts using the configured policy
        """
        if not thought_view.nodes or not thought_view.edges:
            return []

        # Build adjacency map
        adjacency = self._build_adjacency_map(thought_view.edges)
        
        # Find connected components
        components = self._find_connected_components(thought_view.nodes, adjacency)
        
        # Detect patterns in each component
        raw_patterns = []
        for component_nodes in components:
            if len(component_nodes) < 2:
                continue
                
            component_edges = self._get_component_edges(component_nodes, thought_view.edges)
            pattern = self._detect_component_pattern(component_nodes, component_edges)
            
            if pattern:
                match_score = self._calculate_match_score(component_nodes, component_edges)
                pattern_match = PatternMatch(
                    pattern_id=pattern.id,
                    pattern=pattern,
                    match_score=match_score,
                    matched_node_ids=[n.id for n in component_nodes if n.id],
                    matched_edge_ids=[e.id for e in component_edges if e.id],
                    metadata={
                        'component_size': len(component_nodes),
                        'edge_count': len(component_edges),
                        'topology_type': pattern.pattern_type,
                    }
                )
                raw_patterns.append(pattern_match)
        
        # Resolve conflicts using the unified policy
        resolved_patterns = self._resolve_pattern_conflicts(raw_patterns)
        
        return resolved_patterns

    def _build_adjacency_map(self, edges: list[Edge]) -> dict[int, set[int]]:
        """Build adjacency map from edges."""
        adjacency = defaultdict(set)
        for edge in edges:
            if edge.source_node_id and edge.target_node_id:
                adjacency[edge.source_node_id].add(edge.target_node_id)
                adjacency[edge.target_node_id].add(edge.source_node_id)  # Undirected for pattern detection
        return dict(adjacency)

    def _find_connected_components(self, nodes: list[Node], adjacency: dict[int, set[int]]) -> list[list[Node]]:
        """Find connected components in the graph."""
        visited = set()
        components = []
        
        for node in nodes:
            if node.id and node.id not in visited:
                component = []
                self._dfs(node.id, adjacency, visited, component, nodes)
                if component:
                    components.append(component)
        
        return components

    def _dfs(self, node_id: int, adjacency: dict[int, set[int]], visited: set[int], 
             component: list[Node], all_nodes: list[Node]) -> None:
        """Depth-first search to find connected component."""
        visited.add(node_id)
        
        # Find the actual node object
        node_obj = next((n for n in all_nodes if n.id == node_id), None)
        if node_obj:
            component.append(node_obj)
        
        # Visit neighbors
        for neighbor_id in adjacency.get(node_id, set()):
            if neighbor_id not in visited:
                self._dfs(neighbor_id, adjacency, visited, component, all_nodes)

    def _get_component_edges(self, component_nodes: list[Node], all_edges: list[Edge]) -> list[Edge]:
        """Get edges that connect nodes within a component."""
        node_ids = {n.id for n in component_nodes if n.id}
        return [
            edge for edge in all_edges
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids
        ]

    def _detect_component_pattern(self, nodes: list[Node], edges: list[Edge]) -> SubgraphPattern | None:
        """Detect the pattern type for a connected component."""
        node_count = len(nodes)
        edge_count = len(edges)
        
        # Basic pattern classification
        pattern_type = self._classify_topology(node_count, edge_count, edges)
        
        # Create a temporary pattern (in real implementation, this would be stored/retrieved)
        topology_hash = self._calculate_topology_hash(nodes, edges)
        
        return SubgraphPattern(
            pattern_uid=f"temp_{topology_hash}",
            pattern_type=pattern_type,
            node_ids=[n.id for n in nodes if n.id],
            edge_ids=[e.id for e in edges if e.id],
            topology_hash=topology_hash,
            cardinality=node_count,
            edge_count=edge_count,
            pattern_trust=0.5,  # Default trust for detected patterns
        )

    def _classify_topology(self, node_count: int, edge_count: int, edges: list[Edge]) -> str:
        """Classify the topology type based on node/edge counts and structure."""
        if node_count == 2 and edge_count == 1:
            return "dyad"
        elif self._is_chain(node_count, edge_count, edges):
            return "chain"
        elif self._is_star(node_count, edge_count, edges):
            return "star"
        elif self._is_triangle(node_count, edge_count, edges):
            return "triangle"
        elif edge_count == node_count - 1:
            return "tree"
        elif edge_count > node_count:
            return "dense"
        else:
            return "untyped"

    def _is_chain(self, node_count: int, edge_count: int, edges: list[Edge]) -> bool:
        """Check if the component forms a chain (linear structure)."""
        return edge_count == node_count - 1 and self._is_linear(edges)

    def _is_star(self, node_count: int, edge_count: int, edges: list[Edge]) -> bool:
        """Check if the component forms a star (one central node connected to others)."""
        if edge_count != node_count - 1:
            return False
        
        # Count degrees
        degrees = defaultdict(int)
        for edge in edges:
            if edge.source_node_id and edge.target_node_id:
                degrees[edge.source_node_id] += 1
                degrees[edge.target_node_id] += 1
        
        # Should have one node with degree = node_count - 1, others with degree = 1
        degree_counts = list(degrees.values())
        return sorted(degree_counts) == [1] * (node_count - 1) + [node_count - 1]

    def _is_triangle(self, node_count: int, edge_count: int, edges: list[Edge]) -> bool:
        """Check if the component forms a triangle (3 nodes, 3 edges)."""
        return node_count == 3 and edge_count == 3

    def _is_linear(self, edges: list[Edge]) -> bool:
        """Check if edges form a linear structure (no branches)."""
        # Simple check: all nodes have degree <= 2
        degrees = defaultdict(int)
        for edge in edges:
            if edge.source_node_id and edge.target_node_id:
                degrees[edge.source_node_id] += 1
                degrees[edge.target_node_id] += 1
        
        return all(degree <= 2 for degree in degrees.values())

    def _calculate_topology_hash(self, nodes: list[Node], edges: list[Edge]) -> str:
        """Calculate a hash representing the topological structure."""
        # Sort nodes and edges by ID for consistent hashing
        node_ids = sorted(n.id for n in nodes if n.id)
        edge_tuples = sorted(
            (e.source_node_id, e.target_node_id, e.edge_family, e.connect_type, e.connect_semantics)
            for e in edges 
            if e.source_node_id and e.target_node_id
        )
        
        # Create hash input
        hash_input = f"nodes:{node_ids}|edges:{edge_tuples}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]

    def _calculate_match_score(self, nodes: list[Node], edges: list[Edge]) -> float:
        """Calculate how well this component matches a known pattern.
        
        For now, returns a simple score based on connectivity density.
        """
        if not nodes:
            return 0.0
            
        node_count = len(nodes)
        edge_count = len(edges)
        
        # Ideal connectivity score (between 0.5 and 1.5 edges per node)
        if node_count == 0:
            return 0.0
            
        connectivity_ratio = edge_count / node_count
        if 0.5 <= connectivity_ratio <= 1.5:
            return 0.8
        elif connectivity_ratio < 0.5:
            return 0.4  # Sparse
        else:
            return 0.6  # Dense
        
        return 0.5  # Default

    def _resolve_pattern_conflicts(self, patterns: list[PatternMatch]) -> list[PatternMatch]:
        """Resolve conflicts between competing patterns using the unified policy.
        
        Handles both node-level conflicts (multiple patterns on same nodes)
        and graph-level conflicts (overlapping patterns).
        """
        if not patterns:
            return []
        
        # Group patterns by overlapping nodes to identify conflicts
        node_to_patterns = defaultdict(list)
        for pattern in patterns:
            for node_id in pattern.matched_node_ids:
                node_to_patterns[node_id].append(pattern)
        
        # Find conflicting pattern groups (patterns that share nodes)
        conflict_groups = []
        processed_pattern_ids = set()
        non_conflicting_patterns = []
        
        for pattern in patterns:
            if id(pattern) in processed_pattern_ids:
                continue
                
            # Find all patterns that conflict with this one
            conflicting_set = set()
            self._find_conflicting_patterns(pattern, patterns, node_to_patterns, conflicting_set)
            
            # Convert IDs back to pattern objects
            conflicting_patterns = [p for p in patterns if id(p) in conflicting_set]
            
            if len(conflicting_patterns) > 1:
                conflict_groups.append(conflicting_patterns)
                processed_pattern_ids.update(id(p) for p in conflicting_patterns)
            else:
                # No conflicts, keep as-is
                non_conflicting_patterns.extend(conflicting_patterns)
                processed_pattern_ids.update(id(p) for p in conflicting_patterns)
        
        # Resolve each conflict group using the policy
        resolved_patterns = list(non_conflicting_patterns)  # Start with non-conflicting
        
        # Resolve conflicting groups
        for conflict_group in conflict_groups:
            # Use node-level conflict resolution for patterns competing on same nodes
            resolved = self.conflict_policy.resolve_node_conflicts(conflict_group)
            resolved_patterns.extend(resolved)
        
        return resolved_patterns

    def _find_conflicting_patterns(self, start_pattern: PatternMatch, all_patterns: list[PatternMatch],
                                  node_to_patterns: dict[int, list[PatternMatch]], 
                                  result_set: set[int]) -> None:
        """Recursively find all patterns that conflict with the start pattern."""
        start_id = id(start_pattern)
        if start_id in result_set:
            return
            
        result_set.add(start_id)
        
        # Find patterns that share nodes with this pattern
        related_patterns = []
        for node_id in start_pattern.matched_node_ids:
            related_patterns.extend(node_to_patterns.get(node_id, []))
        
        # Remove duplicates
        seen_ids = set()
        unique_related = []
        for rp in related_patterns:
            rp_id = id(rp)
            if rp_id not in seen_ids:
                seen_ids.add(rp_id)
                unique_related.append(rp)
        
        # Recursively find conflicts with related patterns
        for related_pattern in unique_related:
            related_id = id(related_pattern)
            if related_id not in result_set:
                self._find_conflicting_patterns(related_pattern, all_patterns, 
                                              node_to_patterns, result_set)
